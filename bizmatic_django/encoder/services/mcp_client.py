"""Bounded stdio SDK transport behind a replaceable connector interface."""
import asyncio
import os
import json
from dataclasses import dataclass
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
import re
from ipaddress import ip_address
import httpx
from datetime import timedelta
from typing import Protocol

from asgiref.sync import async_to_sync
from django.conf import settings
from django.core.exceptions import ValidationError
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.exceptions import McpError as SDKError


class MCPError(ValidationError):
    pass


@dataclass(frozen=True)
class ConnectionSpec:
    profile: str
    command: str
    args: tuple
    cwd: str | None
    env: dict
    timeout: int


class Connector(Protocol):
    def discover(self) -> list[dict]: ...
    def call(self, name: str, payload: dict, schema: dict) -> dict: ...


@dataclass(frozen=True)
class HTTPConnectionSpec:
    url: str
    headers: dict
    timeout: int


def http_specification(connection):
    url = urlsplit(connection.server_url)
    if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.fragment:
        raise MCPError("Enter an HTTP(S) MCP endpoint URL without embedded credentials or a fragment.")
    if url.scheme == "http":
        try:
            local = ip_address(url.hostname).is_loopback
        except ValueError:
            local = url.hostname.lower() == "localhost"
        if not local:
            raise MCPError("Remote MCP endpoints must use HTTPS. Plain HTTP is supported only for loopback development servers.")
    try:
        headers = json.loads(connection.http_headers or "{}")
    except ValueError:
        raise MCPError("HTTP headers must be a JSON object.") from None
    if not isinstance(headers, dict) or not isinstance(connection.env_http_headers, dict):
        raise MCPError("HTTP headers must be JSON objects.")
    headers = dict(headers)
    for name, variable in connection.env_http_headers.items():
        if not isinstance(variable, str) or not variable or not os.environ.get(variable):
            raise MCPError(f"Missing environment variable for HTTP header {name}.")
        headers[name] = os.environ[variable]
    if connection.bearer_token_env_var:
        token = os.environ.get(connection.bearer_token_env_var)
        if not token:
            raise MCPError(f"Missing bearer token environment variable: {connection.bearer_token_env_var}.")
        if any(name.lower() == "authorization" for name in headers):
            raise MCPError("Use either the bearer token environment variable or an Authorization header, not both.")
        headers["Authorization"] = "Bearer " + token
    for name, value in headers.items():
        if not isinstance(name, str) or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name) or not isinstance(value, str) or any(ord(char) < 32 or ord(char) > 126 for char in value):
            raise MCPError("HTTP headers must have valid names and single-line string values.")
    if len({name.lower() for name in headers}) != len(headers):
        raise MCPError("HTTP header names must be unique (case insensitive).")
    return HTTPConnectionSpec(connection.server_url, headers, max(1, min(connection.timeout_seconds, 300)))


def specification(connection):
    if not settings.ENCODER_LOCAL_ENABLED:
        raise MCPError("Enable ENCODER_LOCAL_ENABLED only on a trusted local development server.")
    if not connection.enabled:
        raise MCPError("This MCP connection is disabled.")
    if connection.transport == "streamable_http":
        return http_specification(connection)
    if connection.transport != "stdio":
        raise MCPError("Choose STDIO or Streamable HTTP.")
    if not isinstance(connection.environment_passthrough, list) or any(not isinstance(name, str) or not name or "=" in name or "\0" in name for name in connection.environment_passthrough):
        raise MCPError("Environment variable passthrough must contain variable names.")
    if connection.command:
        if "\0" in connection.command + connection.working_directory:
            raise MCPError("Executable and working directory cannot contain null characters.")
        try:
            environment = json.loads(connection.environment or "{}")
        except ValueError:
            raise MCPError("MCP environment variables must be a JSON object.") from None
        if not isinstance(environment, dict) or any(not isinstance(k, str) or not k or "=" in k or not isinstance(v, str) or "\0" in k+v for k, v in environment.items()):
            raise MCPError("Environment variables must map valid names to string values.")
        if not isinstance(connection.arguments, list) or any(not isinstance(arg, str) or "\0" in arg for arg in connection.arguments):
            raise MCPError("Arguments must be a JSON list of strings.")
        for name in connection.environment_passthrough:
            if name not in os.environ:
                raise MCPError(f"Missing passthrough environment variable: {name}.")
            environment.setdefault(name, os.environ[name])
        return ConnectionSpec("", connection.command, tuple(connection.arguments), connection.working_directory or None,
                              environment, max(1, min(connection.timeout_seconds, 300)))
    # Compatibility for existing saved profiles; new/edit forms always store inline details.
    profile = settings.ENCODER_STDIO_SERVERS.get(connection.launch_profile)
    if not isinstance(profile, dict) or not isinstance(profile.get("command"), str) or not profile["command"]:
        raise MCPError("The trusted MCP launch profile is unavailable. Configure ENCODER_STDIO_SERVERS on the Django server.")
    names = profile.get("env", [])
    if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
        raise MCPError("The MCP profile's env must list environment variable names.")
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        raise MCPError("Missing MCP server credentials/configuration: " + ", ".join(missing))
    args = profile.get("args", [])
    if not isinstance(args, list) or any(not isinstance(arg, str) for arg in args):
        raise MCPError("The MCP profile's args must be a list of strings.")
    return ConnectionSpec(connection.launch_profile, profile["command"], tuple(args), profile.get("cwd"),
                          {name: os.environ[name] for name in names}, max(1, min(connection.timeout_seconds, 300)))


class StdioConnector:
    def __init__(self, connection):
        self.spec = specification(connection)

    @asynccontextmanager
    async def _streams(self):
        spec = self.spec
        params = StdioServerParameters(command=spec.command, args=list(spec.args), cwd=spec.cwd, env=spec.env)
        async with stdio_client(params) as streams:
            yield streams

    async def _run(self, name=None, payload=None, schema=None):
        spec = self.spec
        # No shell, sampling, elicitation, roots, or model-triggered tool callbacks.
        async with asyncio.timeout(spec.timeout):
            async with self._streams() as (read, write):
                async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=spec.timeout)) as session:
                    await session.initialize()
                    tools, cursor = [], None
                    for _ in range(100):
                        page = await session.list_tools(cursor=cursor)
                        tools.extend(tool.model_dump(mode="json", by_alias=True, exclude_none=True) for tool in page.tools)
                        cursor = page.nextCursor
                        if not cursor:
                            break
                    else:
                        raise MCPError("MCP discovery exceeded 100 pages. Narrow the server's tool catalog.")
                    if name is None:
                        return tools
                    tool = next((row for row in tools if row["name"] == name), None)
                    if tool is None or tool.get("inputSchema") != schema:
                        raise MCPError("The MCP tool or its schema changed. Rediscover tools and review the payload again.")
                    result = await session.call_tool(name, arguments=payload)
                    return result.model_dump(mode="json", by_alias=True, exclude_none=True)

    def _perform(self, **kwargs):
        try:
            return async_to_sync(self._run)(**kwargs)
        except MCPError:
            raise
        except Exception as error:
            # Transport errors may echo credentials; do not persist their raw text.
            def timed_out(exc):
                return (isinstance(exc, (TimeoutError, httpx.TimeoutException))
                        or isinstance(exc, SDKError) and exc.error.code == 408
                        or any(timed_out(child) for child in getattr(exc, "exceptions", [])))
            if timed_out(error):
                raise MCPError("MCP request timed out. Verify the external result before retrying.") from None
            raise MCPError("MCP connection/request failed. Check connection details, required credentials, and server availability.") from None

    def discover(self):
        return self._perform()

    def call(self, name, payload, schema):
        return self._perform(name=name, payload=payload, schema=schema)


class StreamableHTTPConnector(StdioConnector):
    @asynccontextmanager
    async def _streams(self):
        spec = self.spec
        async with streamablehttp_client(spec.url, headers=spec.headers, timeout=spec.timeout, sse_read_timeout=spec.timeout) as streams:
            yield streams[0], streams[1]


def connector(connection) -> Connector:
    return StreamableHTTPConnector(connection) if connection.transport == "streamable_http" else StdioConnector(connection)

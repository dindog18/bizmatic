"""Discovery never approves or invokes a tool."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from ..models import MCPConnection
from . import mcp_client
from .validation import check_schema


def tool(connection, name):
    if not connection.enabled or name not in connection.approved_tools:
        raise ValidationError("Choose an enabled connection and an explicitly permitted tool.")
    row = next((row for row in connection.tools if row["name"] == name), None)
    if row is None:
        raise ValidationError("Discover tools for this connection before choosing an operation.")
    check_schema(row.get("inputSchema"))
    return row


def discover(connection):
    revision = connection.updated_at
    try:
        tools = mcp_client.connector(connection).discover()
        for row in tools:
            check_schema(row.get("inputSchema"))
        with transaction.atomic():
            current = MCPConnection.objects.select_for_update().get(pk=connection.pk)
            if current.updated_at != revision:
                raise ValidationError("Connection settings changed during discovery. Test again.")
            current.tools = tools
            # Removed/changed tools lose approval; new tools always need approval.
            unchanged = {row["name"] for row in tools if row in current.tools and row in connection.tools}
            current.approved_tools = [name for name in current.approved_tools if name in unchanged]
            current.discovery_error = ""
            current.discovered_at = timezone.now()
            current.save()
            return current
    except ValidationError as error:
        MCPConnection.objects.filter(pk=connection.pk, updated_at=revision).update(discovery_error="; ".join(error.messages))
        raise

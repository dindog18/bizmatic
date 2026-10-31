"""Signed payload review, atomic attempt claims, explicit retries, no auto-execution."""
import hashlib
import json
import os
import uuid

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from document_extraction.models import Document
from router.models import DocumentRoute
from router.services.records import _current_attempt
from ..models import EncoderExecution, EncoderJob, MCPConnection
from . import discovery, mcp_client, validation


def identity(job):
    connection = job.connection
    profile = settings.ENCODER_STDIO_SERVERS.get(connection.launch_profile, {})
    content = {"job": job.pk, "revision": job.updated_at.isoformat(), "payload": job.prepared_payload,
               "schema": job.tool_schema, "tool": job.tool_name, "connection": connection.pk,
               "connection_revision": connection.updated_at.isoformat(), "profile": profile,
               "command": connection.command, "arguments": connection.arguments, "cwd": connection.working_directory,
               "inline_environment": connection.environment,
               "passthrough": {name: os.environ.get(name, "") for name in connection.environment_passthrough},
               "transport": connection.transport, "url": connection.server_url, "http_headers": connection.http_headers,
               "bearer_env": connection.bearer_token_env_var, "bearer_value": os.environ.get(connection.bearer_token_env_var, ""),
               "header_env": connection.env_http_headers,
               "header_values": {str(name): os.environ.get(variable, "") for name, variable in connection.env_http_headers.items()},
               # Only the final digest leaves this function; never persist credential values.
               "environment": {name: os.environ.get(name, "") for name in profile.get("env", [])},
               "idempotency_field": job.idempotency_field}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def review_token(job):
    if job.status != "ready" or not job.connection_id:
        return ""
    return signing.dumps({"identity": identity(job), "request_id": str(uuid.uuid4()), "job": job.pk}, salt="encoder-execute")


def route_approved(job):
    route = job.route
    _current_attempt(route.routing_log)
    if (route.review_status != "approved" or job.document.review_status != "approved"
            or not route.destination.is_active or route.destination.module_name != "encoder"
            or route.destination.target_model != "EncoderJob" or route.processing_status != "completed"):
        raise ValidationError("Approve the current source document and Encoder route before executing.")


def execute(job_id, token, *, confirmed=False, reconciled=False):
    if confirmed is not True:
        raise ValidationError("Explicitly confirm the reviewed payload before executing an MCP tool.")
    try:
        reviewed = signing.loads(token, salt="encoder-execute", max_age=1800)
    except (signing.BadSignature, TypeError):
        raise ValidationError("Review and validate the payload again; execution confirmation expired or is invalid.") from None
    with transaction.atomic():
        initial = EncoderJob.objects.get(pk=job_id)
        # Same lock order as Router/extraction prevents a simultaneous reroute.
        Document.objects.select_for_update().get(pk=initial.document.pk)
        DocumentRoute.objects.select_for_update().get(pk=initial.route_id)
        job = EncoderJob.objects.select_for_update().select_related("connection", "route__routing_log__source_document", "route__destination").get(pk=job_id)
        if reviewed.get("job") != job.pk:
            raise ValidationError("This confirmation belongs to another job.")
        previous = EncoderExecution.objects.filter(request_id=reviewed["request_id"]).first()
        if previous:
            return previous  # A browser replay never causes another external call.
        MCPConnection.objects.select_for_update().get(pk=job.connection_id)
        job.connection.refresh_from_db()
        if job.status != "ready" or reviewed.get("identity") != identity(job):
            raise ValidationError("The payload or connection changed. Review and validate again.")
        route_approved(job)
        discovery.tool(job.connection, job.tool_name)
        issues = validation.errors(job.prepared_payload, job.tool_schema)
        if issues:
            raise ValidationError("Resolve payload validation issues before executing.")
        last = job.executions.filter(status="unknown", reconciled_at__isnull=True).first()
        if last and not reconciled:
            if (not job.idempotency_field or last.connection_id != job.connection_id or last.tool_name != job.tool_name
                    or last.payload != job.prepared_payload):
                raise ValidationError("The previous external outcome is unknown. Verify externally that it did not succeed, then confirm reconciliation before retrying.")
        if reconciled:
            job.executions.filter(status="unknown", reconciled_at__isnull=True).update(reconciled_at=timezone.now())
        attempt = EncoderExecution.objects.create(request_id=reviewed["request_id"], job=job, cycle=job.cycle,
            connection=job.connection, tool_name=job.tool_name, tool_schema=job.tool_schema,
            payload=job.prepared_payload, connection_snapshot={"name": job.connection.name,
                "launch_profile": job.connection.launch_profile, "revision": job.connection.updated_at.isoformat()})
        job.status = "processing"
        job.save(update_fields=["status", "updated_at"])
    # Release database locks before bounded subprocess I/O. The job is now claimed.
    invoked = False
    try:
        client = mcp_client.connector(job.connection)
        live = next((row for row in client.discover() if row["name"] == job.tool_name), None)
        if live is None or live.get("inputSchema") != job.tool_schema:
            raise ValidationError("The live tool schema changed. Rediscover tools and select the operation again.")
        invoked = True
        attempt.response = client.call(job.tool_name, job.prepared_payload, job.tool_schema)
        if attempt.response.get("isError"):
            attempt.status = "unknown"
            attempt.error_message = "The MCP tool reported an error. Review the response and verify whether any external change occurred."
        else:
            attempt.status = "completed"
    except Exception as error:
        attempt.status = "unknown" if invoked else "failed"
        attempt.error_message = "; ".join(error.messages) if isinstance(error, ValidationError) else "MCP execution failed. Check the server configuration and availability."
    attempt.finished_at = timezone.now()
    with transaction.atomic():
        attempt.save()
        EncoderJob.objects.filter(pk=job.pk, status="processing").update(
            status="completed" if attempt.status == "completed" else "failed", last_error=attempt.error_message,
            updated_at=timezone.now())
    return attempt

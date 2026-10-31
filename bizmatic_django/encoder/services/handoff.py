"""Prepare a rule-configured Encoder draft; external execution always remains explicit."""
from django.core.exceptions import ValidationError
from ..models import EncoderJob, MCPConnection
from . import mapping, chat


def create_job(route):
    if route.destination.target_model != "EncoderJob":
        raise ValidationError("Choose Encoder job as the Encoder routing target.")
    job, created = EncoderJob.objects.get_or_create(route=route)
    if not created:
        return job  # Never regenerate a prepared payload or repeat a paid request on replay.
    config = route.encoder_config
    if not config:
        return job  # Legacy/manual routes retain their existing operation selector.
    try:
        if config.get("error"):
            raise ValidationError(config["error"])
        connection = MCPConnection.objects.filter(pk=config.get("connection_id"), enabled=True).first()
        if connection is None:
            raise ValidationError("The routing rule's MCP connection is unavailable. Review it in Document routing.")
        job = mapping.select(job.pk, connection, config.get("tool_name", ""), job.updated_at.isoformat())
        if job.validation_errors:
            answer = chat.ask(job.pk, "Prepare the encoding payload from this document for the routing rule's selected MCP operation. Use supported values only. Flag missing or uncertain required values and ask me how to resolve them.", preparation=True, revision=job.updated_at.isoformat())
            job.refresh_from_db()
            if answer.error_message and job.updated_at.isoformat() == answer.base_revision:
                job.last_error = answer.error_message
                job.status = "needs_review"
                job.save()
            elif answer.proposal.get("payload") is not None or answer.proposal.get("mappings") is not None:
                job = chat.prepare(job.pk, answer.pk)
    except (ValidationError, ValueError) as error:
        job.refresh_from_db()
        if job.status not in {"processing", "completed"}:
            job.status = "needs_review"
            job.last_error = "; ".join(error.messages) if isinstance(error, ValidationError) else str(error)
            job.save()
    return job

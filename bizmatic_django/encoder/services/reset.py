"""Start a fresh local cycle without deleting audit records or undoing ERP writes."""
from django.core.exceptions import ValidationError
from django.db import transaction

from ..models import EncoderJob, EncoderReset
from . import validation


@transaction.atomic
def reset(job_id, revision, *, confirmed=False):
    job = EncoderJob.objects.select_for_update().get(pk=job_id)
    from router.services.configuration import check_revision
    check_revision(job, revision)
    if confirmed is not True:
        raise ValidationError("Confirm the reset. Previous external changes will not be undone.")
    if (job.status == "processing" or job.executions.filter(status="processing").exists()
            or job.chat_messages.filter(status="processing").exists()):
        raise ValidationError("Wait for running chat and execution requests to finish before resetting.")
    EncoderReset.objects.create(job=job, cycle=job.cycle, snapshot={
        "status": job.status, "connection_id": job.connection_id, "tool_name": job.tool_name,
        "tool_schema": job.tool_schema, "field_mappings": job.field_mappings,
        "prepared_payload": job.prepared_payload, "validation_errors": job.validation_errors,
        "last_error": job.last_error, "revision": job.updated_at.isoformat(),
        "idempotency_key": str(job.idempotency_key), "idempotency_field": job.idempotency_field,
    })
    job.cycle += 1
    job.prepared_payload = {}
    job.field_mappings = {}
    job.last_error = ""
    job.validation_errors = validation.errors({}, job.tool_schema) if job.tool_name else []
    job.status = "needs_review" if job.tool_name else "pending"
    job.save()
    # Keep the stable idempotency key and ALL attempts: unknown-outcome checks
    # continue across cycles, preventing reset from bypassing reconciliation.
    return job

"""Reusable source paths, explicit defaults and bounded transformations."""
import json
import math
from copy import deepcopy
from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import transaction

from router.services.configuration import check_revision
from ..models import EncoderJob, EncoderMapping
from . import discovery, validation

TRANSFORMS = ("identity", "strip", "upper", "lower", "integer", "number", "date_dmy", "date_mdy")
MISSING = object()


def source_data(job):
    # Always use the exact already-extracted routing input, never run OCR again.
    text = job.route.routing_log.input_text
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {"data": parsed, "text": text}
    except (ValueError, TypeError):
        return {"text": text}


def source_value(data, path):
    try:
        for key in path.split("."):
            data = data[int(key)] if isinstance(data, list) else data[key]
        return data
    except (KeyError, IndexError, TypeError, ValueError):
        return MISSING


def check_mappings(mappings):
    if not isinstance(mappings, dict) or len(mappings) > 200:
        raise ValidationError("Mappings must be an object with at most 200 fields.")
    for field, rule in mappings.items():
        if not isinstance(rule, dict) or set(rule) - {"source", "default", "transform"}:
            raise ValidationError(f"{field}: use source, default and transform only.")
        if not isinstance(rule.get("source", ""), str) or rule.get("transform", "identity") not in TRANSFORMS:
            raise ValidationError(f"{field}: choose a source path and supported transformation.")


def build(data, mappings):
    check_mappings(mappings)
    payload, issues = {}, []
    for field, rule in mappings.items():
        value = source_value(data, rule["source"]) if rule.get("source") else MISSING
        if value is MISSING or value is None or value == "":
            value = rule.get("default", MISSING)
        if value is MISSING:
            continue
        transform = rule.get("transform", "identity")
        try:
            if transform in {"strip", "upper", "lower"}:
                value = getattr(str(value), transform)()
            elif transform == "integer":
                if isinstance(value, bool) or float(value) != int(value):
                    raise ValueError
                value = int(value)
            elif transform == "number":
                if isinstance(value, bool):
                    raise ValueError
                value = float(value)
                if not math.isfinite(value):
                    raise ValueError
            elif transform in {"date_dmy", "date_mdy"}:
                value = datetime.strptime(str(value), "%d/%m/%Y" if transform == "date_dmy" else "%m/%d/%Y").date().isoformat()
            payload[field] = value
        except (ValueError, TypeError, OverflowError):
            issues.append({"field": field, "message": f"Cannot apply {transform}. Correct this source value."})
    return payload, issues


def editable(job, revision):
    check_revision(job, revision)
    if job.status in {"processing", "completed"}:
        raise ValidationError("This job is processing or completed and cannot be edited.")


def validate(job):
    try:
        json.dumps(job.prepared_payload, allow_nan=False)
    except (ValueError, TypeError):
        raise ValidationError("Use valid JSON values and finite numbers in the prepared payload.") from None
    if not job.connection_id or not job.tool_name:
        raise ValidationError("Choose a connection and operation first.")
    current = discovery.tool(job.connection, job.tool_name)
    if current["inputSchema"] != job.tool_schema:
        raise ValidationError("The tool schema changed. Select the operation again and review the new fields.")
    if job.idempotency_field:
        field = job.tool_schema.get("properties", {}).get(job.idempotency_field, {})
        if field.get("type") != "string":
            raise ValidationError("The idempotency field must be a declared string input parameter.")
        job.prepared_payload[job.idempotency_field] = str(job.idempotency_key)
    job.validation_errors = validation.errors(job.prepared_payload, job.tool_schema)
    job.status = "needs_review" if job.validation_errors else "ready"
    job.last_error = ""
    job.save()
    return job


@transaction.atomic
def select(job_id, connection, name, revision):
    job = EncoderJob.objects.select_for_update().get(pk=job_id)
    editable(job, revision)
    row = discovery.tool(connection, name)
    profile = EncoderMapping.objects.filter(connection=connection, tool_name=name).first()
    job.connection, job.tool_name, job.tool_schema = connection, name, row["inputSchema"]
    data = source_data(job)
    job.field_mappings = profile.field_mappings if profile else {
        name: {"source": name, "transform": "identity"}
        for name in job.tool_schema.get("properties", {}) if name in data and name != "text"
    }
    job.idempotency_field = profile.idempotency_field if profile else ""
    job.prepared_payload, issues = build(source_data(job), job.field_mappings)
    validate(job)
    if issues:
        job.validation_errors = issues + job.validation_errors
        job.status = "needs_review"
        job.save()
    return job


@transaction.atomic
def save(job_id, revision, *, payload=None, mappings=None, reusable=False):
    job = EncoderJob.objects.select_for_update().select_related("connection").get(pk=job_id)
    editable(job, revision)
    issues = []
    if mappings is not None:
        job.prepared_payload, issues = build(source_data(job), mappings)
        job.field_mappings = mappings
    else:
        if not isinstance(payload, dict):
            raise ValidationError("Enter a JSON object for the prepared payload.")
        job.prepared_payload = deepcopy(payload)
    validate(job)
    if issues:
        job.validation_errors = issues + job.validation_errors
        job.status = "needs_review"
        job.save()
    if reusable:
        EncoderMapping.objects.update_or_create(connection=job.connection, tool_name=job.tool_name,
            defaults={"field_mappings": job.field_mappings, "idempotency_field": job.idempotency_field})
    return job

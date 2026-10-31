"""Small validated configuration writes, kept separate from HTTP handlers."""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404

from ..forms import DestinationForm, RuleForm
from ..models import RoutingDestination, RoutingRule

MODELS = {"destinations": RoutingDestination, "rules": RoutingRule}
FORMS = {"destinations": DestinationForm, "rules": RuleForm}


def check_revision(record, revision):
    if record.updated_at.isoformat() != revision:
        raise ValidationError("This record changed. Reload before saving again.", code="conflict")


def save(kind, data, record_id=None):
    try:
        with transaction.atomic():
            row = get_object_or_404(MODELS[kind].objects.select_for_update(), pk=record_id) if record_id else None
            if row and kind == "destinations" and row.is_deleted:
                raise ValidationError("This destination has been deleted.")
            if row:
                check_revision(row, data.get("revision"))
            values = dict(data)
            if kind == "rules":
                values["destination"] = values.get("destination_id")
            form = FORMS[kind](values, instance=row)
            if not form.is_valid():
                raise ValidationError(form.errors.as_text())
            return form.save()
    except IntegrityError as exc:
        raise ValidationError("This module and model already have a destination.") from exc


@transaction.atomic
def toggle(kind, record_id, data):
    row = get_object_or_404(MODELS[kind].objects.select_for_update(), pk=record_id)
    check_revision(row, data.get("revision"))
    if kind == "destinations" and row.is_deleted:
        raise ValidationError("This destination has been deleted.")
    if type(data.get("is_active")) is not bool:
        raise ValidationError("Active must be true or false.")
    row.is_active = data["is_active"]
    row.save(update_fields=["is_active", "updated_at"])
    return row


@transaction.atomic
def delete(kind, record_id, data):
    """Delete configuration only; immutable routing snapshots/history are retained."""
    row = get_object_or_404(MODELS[kind].objects.select_for_update(), pk=record_id)
    check_revision(row, data.get("revision"))
    if data.get("confirmed") is not True:
        raise ValidationError("Confirm deletion before removing this configuration.")
    if kind == "destinations":
        if data.get("delete_associated_rules") is not True:
            raise ValidationError("Reload and confirm the updated warning that all associated routing rules will also be deleted.")
        # Keep a tombstone for existing/in-flight routes; remove live configuration atomically.
        if row.is_deleted:
            raise ValidationError("This destination has already been deleted.")
        row.rules.all().delete()
        row.is_active = False
        row.is_deleted = True
        row.save(update_fields=["is_active", "is_deleted", "updated_at"])
    else:
        row.delete()
    return record_id

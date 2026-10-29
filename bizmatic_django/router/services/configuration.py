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
    if type(data.get("is_active")) is not bool:
        raise ValidationError("Active must be true or false.")
    row.is_active = data["is_active"]
    row.save(update_fields=["is_active", "updated_at"])
    return row

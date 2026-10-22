"""Human review of saved routing decisions; no destination-module writes."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404

from ..models import DocumentRoute, LLMRoutingLog, RoutingDestination, ReviewStatus
from .configuration import check_revision


def _current_attempt(log):
    if log.status != "completed":
        raise ValidationError("Only completed attempts can be reviewed.")
    if log.source_document.updated_at.isoformat() != log.source_revision:
        raise ValidationError("The source document changed after this attempt. Route it again before approving destinations.")
    if log.source_document.routing_logs.order_by("-created_at", "-pk").first().pk != log.pk:
        raise ValidationError("A newer routing attempt exists. Review the latest attempt.")


@transaction.atomic
def review(route_id, data):
    route = get_object_or_404(DocumentRoute.objects.select_for_update().select_related("routing_log__source_document"), pk=route_id)
    check_revision(route, data.get("revision"))
    decision = data.get("decision")
    if decision not in {"notes", *ReviewStatus.values}:
        raise ValidationError("Choose approve, reject, reopen, or save notes.")
    notes = data.get("review_notes", "")
    if not isinstance(notes, str) or len(notes) > 10000:
        raise ValidationError("Review notes must be text up to 10,000 characters.")
    if decision != "notes":
        _current_attempt(route.routing_log)
        route.review_status = decision
    route.review_notes = notes.strip()
    route.save(update_fields=["review_status", "review_notes", "updated_at"])
    return route


@transaction.atomic
def add_route(log_id, data):
    log = get_object_or_404(LLMRoutingLog.objects.select_for_update().select_related("source_document"), pk=log_id)
    _current_attempt(log)
    destination = get_object_or_404(RoutingDestination, pk=data.get("destination_id"), is_active=True)
    reason = data.get("reason", "")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 10000:
        raise ValidationError("Enter a reason up to 10,000 characters.")
    route, created = DocumentRoute.objects.get_or_create(routing_log=log, destination=destination, defaults={"reason": reason.strip()})
    if not created:
        raise ValidationError("This destination is already included in this attempt.")
    return route


@transaction.atomic
def set_accuracy(log_id, data):
    log = get_object_or_404(LLMRoutingLog.objects.select_for_update(), pk=log_id)
    check_revision(log, data.get("revision"))
    if log.status != "completed" or type(data.get("accurate")) is not bool:
        raise ValidationError("Only a completed attempt can be marked accurate.")
    log.user_selected_accurate = data["accurate"]
    log.save(update_fields=["user_selected_accurate", "updated_at"])
    return log

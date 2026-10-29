"""Extract LLM matches automatically; failed routes can be retried explicitly."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from document_extraction.models import Document
from ..models import DocumentRoute
from .configuration import check_revision
from .records import _current_attempt


def process_matches(log_id):
    """Called once after a new routing result commits, never on request replay."""
    for route_id in DocumentRoute.objects.filter(routing_log_id=log_id).values_list("pk", flat=True):
        try:
            process(route_id, automatic=True)
        except ValidationError as error:
            # Preflight failures (for example a changed source) also need a
            # visible outcome, without replacing a concurrent processing result.
            DocumentRoute.objects.filter(pk=route_id, processing_status="pending").update(
                processing_status="failed", processing_error="; ".join(error.messages), updated_at=timezone.now())


def process(route_id, configuration_id=None, revision=None, *, automatic=False):
    with transaction.atomic():
        initial = get_object_or_404(DocumentRoute.objects.select_related("routing_log"), pk=route_id)
        Document.objects.select_for_update().get(pk=initial.routing_log.source_document_id)
        route = DocumentRoute.objects.select_for_update().select_related("routing_log__source_document", "destination").get(pk=route_id)
        if route.processing_status == "completed":
            return route
        if revision is not None:
            check_revision(route, revision)
        _current_attempt(route.routing_log)
        allowed_reviews = {"pending", "approved"} if automatic else {"approved"}
        if route.review_status not in allowed_reviews:
            raise ValidationError("Approve this route before processing its accounting record.")
        if route.processing_status == "processing":
            raise ValidationError("This route is already processing.", code="conflict")
        if not route.destination.is_active:
            raise ValidationError("This destination is inactive.")
        route.processing_status = "processing"
        route.processing_error = ""
        route.save(update_fields=["processing_status", "processing_error", "updated_at"])
    try:
        from accounts_receivable.services.extraction import execute_route
        modes = {"accounts_payable": "ap", "accounts_receivable": "ar"}
        if route.destination.module_name not in modes:
            raise ValidationError("No extraction handler is installed for this module.")
        execute_route(modes[route.destination.module_name], route, configuration_id, automatic=automatic)
    except Exception as error:
        route.processing_status = "failed"
        route.processing_error = "; ".join(error.messages) if isinstance(error, ValidationError) else "Accounting processing failed. Check the configuration and attempt history."
    else:
        route.processing_status = "completed"
        route.processed_at = timezone.now()
    route.save(update_fields=["processing_status", "processing_error", "processed_at", "updated_at"])
    return route

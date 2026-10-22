"""Database reads and JSON presentation used by the existing routing screens."""

from django.db.models import Exists, OuterRef, Subquery
from django.shortcuts import get_object_or_404

from document_extraction.models import Document
from ..models import DocumentRoute, LLMRoutingLog, RoutingDestination, RoutingRule


def destination(row):
    return {"id": row.pk, "name": row.name, "module_name": row.module_name,
            "target_model": row.target_model, "description": row.description,
            "is_active": row.is_active, "revision": row.updated_at.isoformat()}


def rule(row):
    return {"id": row.pk, "name": row.name, "destination_id": row.destination_id,
            "document_type": row.document_type, "instructions": row.instructions,
            "examples": row.examples, "is_active": row.is_active, "revision": row.updated_at.isoformat()}


def route(row):
    return {"id": row.pk, "log_id": row.routing_log_id, "destination_id": row.destination_id,
            "reason": row.reason, "confidence": float(row.confidence) if row.confidence is not None else None,
            "review_status": row.review_status, "review_notes": row.review_notes,
            "revision": row.updated_at.isoformat()}


def log(row, full=False):
    result = {"id": row.pk, "document_id": row.source_document_id, "provider": row.provider,
              "request_id": str(row.request_id) if row.request_id else None,
              "model_name": row.model_name, "status": row.status, "created": row.created_at.isoformat(),
              "input_tokens": row.input_tokens, "output_tokens": row.output_tokens,
              "processing_time_ms": row.processing_time_ms, "error_message": row.error_message,
              "user_selected_accurate": row.user_selected_accurate, "revision": row.updated_at.isoformat(),
              "source_review_status": row.source_review_status, "confirmed_unapproved": row.confirmed_unapproved,
              "source_text_log": row.source_text_log_id, "source_llm_log": row.source_llm_log_id,
              "source_revision": row.source_revision}
    if full:
        result.update(input_text=row.input_text, prompt_text=row.prompt_text, rules_snapshot=row.rules_snapshot,
                      response_text=row.response_text, request_payload=row.request_payload, response_payload=row.response_payload)
    return result


def workspace_state(screen, record_id):
    # Only detail pages load raw prompts and provider payloads. List queries are bounded.
    attempts = LLMRoutingLog.objects.defer("input_text", "prompt_text", "rules_snapshot", "request_payload", "response_payload", "response_text")
    documents = Document.objects.none()
    if screen == "queue":
        documents = list(Document.objects.filter(Exists(LLMRoutingLog.objects.filter(source_document=OuterRef("pk")))).order_by("-updated_at", "-pk")[:500])
        latest_ids = Document.objects.filter(pk__in=[doc.pk for doc in documents]).annotate(
            latest_log=Subquery(LLMRoutingLog.objects.filter(source_document=OuterRef("pk")).order_by("-created_at", "-pk").values("pk")[:1])
        ).values("latest_log")
        attempts = list(attempts.filter(pk__in=Subquery(latest_ids)).order_by("-created_at", "-pk"))
    elif screen in {"document", "log"}:
        document_id = record_id if screen == "document" else get_object_or_404(LLMRoutingLog, pk=record_id).source_document_id
        documents = [get_object_or_404(Document, pk=document_id)]
        attempts = list(LLMRoutingLog.objects.filter(source_document_id=document_id).order_by("-created_at", "-pk"))
    elif screen == "logs":
        attempts = list(attempts.order_by("-created_at", "-pk")[:500])
        documents = list(Document.objects.filter(pk__in=[row.source_document_id for row in attempts]))
    else:
        attempts = []
    return {
        "destinations": [destination(row) for row in RoutingDestination.objects.all()],
        "rules": [rule(row) for row in RoutingRule.objects.all()],
        "documents": [{"id": doc.pk, "name": doc.file_name, "type": doc.document_type,
                       "party": f"Document #{doc.pk}", "batch": f"Batch #{doc.fk_batch_no_id}" if doc.fk_batch_no_id else "No batch",
                       "created": doc.created_at.isoformat(), "revision": doc.updated_at.isoformat(), "text": ""} for doc in documents],
        "logs": [log(row, full=screen in {"document", "log"}) for row in attempts],
        "routes": [route(row) for row in DocumentRoute.objects.filter(routing_log_id__in=[row.pk for row in attempts])],
    }

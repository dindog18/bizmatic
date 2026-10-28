"""Select saved text, create attempt snapshots, and persist each routing result.

Like document extraction, a request waits for a bounded group of async provider
calls. Every document gets its own durable attempt; one failure does not erase
successful siblings. Valid matches then start destination-module extraction.
"""

import logging
from time import perf_counter

from asgiref.sync import async_to_sync, sync_to_async
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from document_extraction.models import Batch, Document, LLMExtractionLog
from document_extraction.utils.concurrency import concurrent_map
from ..models import DocumentRoute, LLMRoutingLog, RoutingRule
from ..schemas.routing import ExecutionRequest
from . import handoff, llm

logger = logging.getLogger(__name__)


class ConfirmationRequired(ValidationError):
    def __init__(self, message, documents):
        super().__init__(message)
        self.documents = documents


def document_metadata(document):
    return {"id": document.pk, "name": document.file_name,
            "review_status": document.review_status, "revision": document.updated_at.isoformat()}


def select_text(document):
    """Prefer a human-marked accurate extraction, then the newest usable attempt.

    Never concatenate alternate OCR results for the same source document.
    The chosen input is copied into LLMRoutingLog before calling a provider.
    """
    candidates = [row for row in [*document.text_logs.all(), *document.llm_logs.all()]
                  if (row.markdown_text or "").strip() and not row.error_message
                  and (not isinstance(row, LLMExtractionLog) or row.status == "completed")]
    if not candidates:
        raise ValidationError(f"Document #{document.pk} has no successful extracted text. Extract or edit its text before routing.")
    return max(candidates, key=lambda row: (row.user_selected_accurate, row.updated_at, row.pk))


def rule_snapshot():
    return [{"rule_no": rule.pk, "name": rule.name, "document_type": rule.document_type,
             "instructions": rule.instructions, "examples": rule.examples,
             "destination_id": rule.destination_id, "destination_name": rule.destination.name,
             "module_name": rule.destination.module_name, "target_model": rule.destination.target_model,
             "description": rule.destination.description}
            for rule in RoutingRule.objects.select_related("destination").filter(
                is_active=True, destination__is_active=True).order_by("pk")]


def _register(request: ExecutionRequest, config):
    with transaction.atomic():
        queryset = Document.objects.select_for_update().prefetch_related("text_logs", "llm_logs").order_by("pk")
        if request.batch_id is not None:
            if not Batch.objects.filter(pk=request.batch_id).exists():
                raise ValidationError("This batch no longer exists.")
            documents = list(queryset.filter(fk_batch_no_id=request.batch_id))
        else:
            documents = list(queryset.filter(pk__in=request.document_ids))
        if not documents or len(documents) > config.max_documents:
            raise ValidationError(f"Select between 1 and {config.max_documents} documents per routing request.")
        existing = list(LLMRoutingLog.objects.filter(request_id=request.request_id).order_by("source_document_id"))
        ids = {row.pk for row in documents}
        if existing:
            if {row.source_document_id for row in existing} != ids:
                raise ValidationError("This request ID belongs to a different selection. Reload and try again.")
            return existing, False
        metadata = [document_metadata(doc) for doc in documents]
        if ids != set(request.document_ids) or any(request.revisions.get(str(doc.pk)) != doc.updated_at.isoformat() for doc in documents):
            raise ConfirmationRequired("The documents or their reviews changed. Review the current selection and confirm again.", metadata)
        if any(doc.review_status != "approved" for doc in documents) and not request.allow_unapproved:
            raise ConfirmationRequired("Some documents are not approved. Confirm that you want to route them anyway.", metadata)
        if any(doc.processing_status in {"queued", "processing"} for doc in documents):
            raise ValidationError("Wait for document extraction to finish before routing.")
        if LLMRoutingLog.objects.filter(source_document_id__in=ids, status__in=["queued", "processing"]).exists():
            raise ValidationError("A selected document is already being routed. Wait for that attempt to finish.")
        if DocumentRoute.objects.filter(routing_log__source_document_id__in=ids, processing_status="processing").exists():
            raise ValidationError("Wait for AP/AR extraction to finish before rerunning routing.")
        rules = rule_snapshot()
        if not rules:
            raise ValidationError("Add an active routing destination and an active routing rule before running documents.")
        logs = []
        for document in documents:
            source = select_text(document)
            text = source.markdown_text
            if len(text) > config.max_input_characters:
                raise ValidationError(f"Document #{document.pk} exceeds ROUTER_MAX_INPUT_CHARACTERS. Its text was not truncated or sent.")
            prompt, payload = llm.request_payload(config, text, rules)
            logs.append(LLMRoutingLog.objects.create(
                request_id=request.request_id, source_document=document,
                source_text_log=source if not isinstance(source, LLMExtractionLog) else None,
                source_llm_log=source if isinstance(source, LLMExtractionLog) else None,
                source_review_status=document.review_status, source_revision=document.updated_at.isoformat(),
                confirmed_unapproved=document.review_status != "approved" and request.allow_unapproved,
                input_text=text, prompt_text=prompt, rules_snapshot=rules, request_payload=payload,
                provider=config.provider, model_name=config.model, status="queued",
            ))
        return logs, True


def _save_result(log, result, parsed, error, duration):
    with transaction.atomic():
        # Only validated configured destination IDs reach this write.
        if parsed is not None:
            DocumentRoute.objects.bulk_create([
                DocumentRoute(routing_log=log, destination_id=row.destination_id,
                              reason=row.reason.strip(), confidence=row.confidence)
                for row in parsed.routes
            ])
        log.response_payload = result
        log.response_text = llm.response_text(log.provider, result) if result else None
        log.processing_time_ms = duration
        log.status = "failed" if error else "completed"
        log.error_message = error
        if result:
            reported_model = result.get("model") or result.get("modelVersion")
            if isinstance(reported_model, str) and len(reported_model) <= 150:
                log.model_name = reported_model
            for name, value in llm.usage(result).items():
                # Malformed usage metadata must not lose the original response.
                setattr(log, name, value if type(value) is int and value >= 0 else None)
        log.save()
    logger.info("document=%s routing_log=%s status=%s destinations=%s duration_ms=%s",
                log.source_document_id, log.pk, log.status, len(parsed.routes) if parsed else 0, duration)


async def _run(logs, config):
    async def run_one(log):
        started = perf_counter()
        result, parsed, error = {}, None, None
        await sync_to_async(LLMRoutingLog.objects.filter(pk=log.pk).update)(status="processing", updated_at=timezone.now())
        try:
            result = await llm.invoke(config, log.request_payload)
            parsed = llm.parse_response(config.provider, result, {row["destination_id"] for row in log.rules_snapshot})
        except Exception as exc:
            error = f"Routing failed: {type(exc).__name__}: {str(exc)}"
            logger.warning("document=%s routing_log=%s failed type=%s", log.source_document_id, log.pk, type(exc).__name__)
        await sync_to_async(_save_result)(log, result, parsed, error, round((perf_counter() - started) * 1000))
        if parsed is not None and not error:
            # Commit the routing snapshot before accounting reads it. Each route
            # keeps its own extraction outcome; a failure must not lose siblings.
            await sync_to_async(handoff.process_matches)(log.pk)
    await concurrent_map(run_one, logs, config.concurrency)


def execute(request: ExecutionRequest):
    """Called from POST only; preflight failures create no attempts or assignments."""
    config = llm.settings()
    try:
        logs, is_new = _register(request, config)
    except IntegrityError as exc:
        raise ValidationError("A selected document is already being routed. Reload to see its latest attempt.") from exc
    if is_new:
        try:
            async_to_sync(_run)(logs, config)
        except Exception:
            # Preserve completed siblings and end unfinished attempts on infrastructure failure.
            LLMRoutingLog.objects.filter(pk__in=[log.pk for log in logs], status__in=["queued", "processing"]).update(
                status="failed", error_message="Routing execution stopped before a result could be saved.", updated_at=timezone.now())
            logger.exception("Routing execution stopped request=%s", request.request_id)
    return list(LLMRoutingLog.objects.filter(pk__in=[log.pk for log in logs]).order_by("pk"))

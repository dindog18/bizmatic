"""Read-only queries, pagination and template context for document pages."""

from typing import Any

from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404

from ..models import Batch, Document, DocExtractionLog, LLMExtractionLog, ProcessingStatus, ReviewStatus, LLMRunStatus
from ..schemas.presentation import BatchDisplay, DocumentDisplay, LogDisplay


PROCESSING_STYLES = {
    "queued": ("secondary", "clock"), "processing": ("info", "sync-alt"),
    "completed": ("success", "check-circle"), "needs_review": ("warning", "clipboard-check"),
    "failed": ("danger", "exclamation-circle"),
}
REVIEW_COLORS = {"pending": "secondary", "approved": "success", "rejected": "danger"}


def _document(document: Document) -> DocumentDisplay:
    image = (document.mime_type or "").startswith("image/")
    return DocumentDisplay(
        record=document,
        processing_label=str(dict(ProcessingStatus.choices).get(document.processing_status, document.processing_status)),
        processing_color=PROCESSING_STYLES.get(document.processing_status, ("secondary", "clock"))[0],
        review_label=str(dict(ReviewStatus.choices).get(document.review_status, document.review_status)),
        review_color=REVIEW_COLORS.get(document.review_status, "secondary"),
        extension=document.file_name.rsplit(".", 1)[-1].upper(),
        icon="file-image" if image else ("file-pdf" if document.mime_type == "application/pdf" else "file-alt"),
        color="info" if image else "danger",
    )


def _log(log: DocExtractionLog | LLMExtractionLog) -> LogDisplay:
    prefix = "llm" if isinstance(log, LLMExtractionLog) else "doc"
    routes = {f"{action}_route": f"DOC_EXTRACTION:{prefix}_extraction_{action}"
              for action in ("detail", "edit", "accuracy", "delete")}
    if isinstance(log, LLMExtractionLog):
        return LogDisplay(
            record=log, log_no=log.pk,
            status_label=str(dict(LLMRunStatus.choices).get(log.status, log.status)),
            color=PROCESSING_STYLES.get(log.status, ("secondary", "clock"))[0],
            **routes,
        )
    return LogDisplay(record=log, log_no=log.pk, **routes)


def _summary(documents):
    # Count in SQL instead of loading all documents into memory.
    counts = dict(documents.order_by().values("processing_status").annotate(total=Count("pk")).values_list("processing_status", "total"))
    return [{"label": label, "count": counts.get(value, 0),
             "color": PROCESSING_STYLES[value][0], "icon": PROCESSING_STYLES[value][1]}
            for value, label in ProcessingStatus.choices]


def _batches():
    return Batch.objects.annotate(
        count=Count("documents"),
        completed=Count("documents", filter=Q(documents__processing_status="completed")),
        failed=Count("documents", filter=Q(documents__processing_status="failed")),
    ).order_by("-created_at", "-pk")


def _batch(batch: Batch) -> BatchDisplay:
    # SQL annotations are available at runtime, but are not declared model fields.
    return BatchDisplay(
        record=batch, count=getattr(batch, "count"),
        completed=getattr(batch, "completed"), failed=getattr(batch, "failed"),
    )


def _page(params, queryset):
    # Keep filters in pagination links; malformed page numbers fall back safely.
    page_number = params.get("page")
    params = params.copy()
    params.pop("page", None)
    return {"page_obj": Paginator(queryset, 25).get_page(page_number),
            "page_query": params.urlencode()}


def _number(value):
    # Reject invalid or oversized IDs before passing them to a database integer column.
    return int(value) if value.isascii() and value.isdecimal() and len(value) <= 19 and int(value) <= 2**63 - 1 else None


def _routing_document(document):
    """Presentation metadata for the browser-only routing confirmation."""
    return {"id": document.pk, "name": document.file_name,
            "review_status": document.review_status}


def document_list_context(params) -> dict[str, Any]:
    filters = {key: params.get(key, "").strip() for key in ("q", "type", "batch", "status", "review")}
    documents = Document.objects.order_by("-created_at", "-pk")
    if filters["q"]:
        match = Q(file_name__icontains=filters["q"])
        number = _number(filters["q"].removeprefix("#"))
        if number is not None:
            match |= Q(pk=number)
        documents = documents.filter(match)
    for key, field in (("type", "document_type"), ("status", "processing_status"), ("review", "review_status")):
        if filters[key]:
            documents = documents.filter(**{field: filters[key]})
    if filters["batch"] == "unassigned":
        documents = documents.filter(fk_batch_no__isnull=True)
    elif filters["batch"]:
        number = _number(filters["batch"])
        documents = documents.filter(fk_batch_no_id=number) if number is not None else documents.none()
    page = _page(params, documents)
    return {
        "page_title": "Documents", "section": "documents", **page,
        "documents": [_document(doc) for doc in page["page_obj"]],
        "routing_documents": [_routing_document(doc) for doc in page["page_obj"]],
        "summary": _summary(documents), "filters": filters,
        "batches": Batch.objects.order_by("-created_at", "-pk"),
        "document_types": Document.objects.order_by("document_type").values_list("document_type", flat=True).distinct(),
        "processing_choices": ProcessingStatus.choices, "review_choices": ReviewStatus.choices,
    }


def document_detail_context(document_no: int) -> dict[str, Any]:
    document = get_object_or_404(Document, pk=document_no)
    return {
        "page_title": f"Document #{document_no}", "section": "documents",
        "document": _document(document),
        "routing_documents": [_routing_document(document)],
        "text_logs": [_log(log) for log in DocExtractionLog.objects.filter(fk_document_no=document).order_by("-created_at", "-pk")],
        "runs": [_log(log) for log in LLMExtractionLog.objects.filter(fk_document_no=document).order_by("-created_at", "-pk")],
    }


def extraction_detail_context(document_no: int, log_no: int, model: type[DocExtractionLog] | type[LLMExtractionLog], *, edit_mode: bool = False) -> dict[str, Any]:
    # Match both IDs so a log can only be read under its owning document.
    log = get_object_or_404(model.objects.select_related("fk_document_no"), pk=log_no, fk_document_no_id=document_no)
    is_llm = model is LLMExtractionLog
    kind = "LLM" if is_llm else "Text"
    return {
        "page_title": f"Edit Markdown · {kind} #{log_no}" if edit_mode else f"{kind} extraction #{log_no}", "section": "documents",
        "document": log.fk_document_no, "log": _log(log), "kind": kind, "is_llm": is_llm,
        "edit_mode": edit_mode,
    }


def batch_list_context(params) -> dict[str, Any]:
    page = _page(params, _batches())
    return {
        "page_title": "Batches", "section": "batches", **page,
        "batches": [_batch(batch) for batch in page["page_obj"]],
    }


def batch_detail_context(params, batch_no: int) -> dict[str, Any]:
    batch = get_object_or_404(_batches(), pk=batch_no)
    documents = Document.objects.filter(fk_batch_no=batch).order_by("-created_at", "-pk")
    page = _page(params, documents)
    return {
        "page_title": f"Batch #{batch_no}", "section": "batches", **page,
        "batch": _batch(batch), "documents": [_document(doc) for doc in page["page_obj"]],
        "routing_documents": [_routing_document(doc) for doc in documents],
        "rerun_disabled": not documents.exists() or documents.filter(processing_status__in=[ProcessingStatus.QUEUED, ProcessingStatus.PROCESSING]).exists(),
        "summary": _summary(documents),
    }

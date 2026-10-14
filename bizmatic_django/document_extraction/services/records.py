"""Validated document and extraction writes, with terminal logs."""

import logging
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404

from ..models import Document, DocExtractionLog, LLMExtractionLog, ProcessingStatus, ReviewStatus

logger = logging.getLogger(__name__)
LogModel = type[DocExtractionLog] | type[LLMExtractionLog]


def get_document(document_no: int) -> Document:
    return get_object_or_404(Document, pk=document_no)


def get_extraction(document_no: int, log_no: int | None, model: LogModel) -> DocExtractionLog | LLMExtractionLog:
    # A log can only be managed under its owning document.
    return get_object_or_404(model, pk=log_no, fk_document_no_id=document_no)


def _locked_document(document_no: int) -> Document:
    document = get_object_or_404(Document.objects.select_for_update(), pk=document_no)
    # Upload callbacks still own these records until their extraction finishes.
    if document.processing_status in (ProcessingStatus.QUEUED, ProcessingStatus.PROCESSING):
        raise ValidationError("Wait for document processing to finish before changing this record.", code="conflict")
    return document


def _check_revision(record, revision: str) -> None:
    if record.updated_at.isoformat() != revision:
        raise ValidationError("This record changed while you were editing. Reload it before saving again.", code="conflict")


def _pending(document: Document) -> None:
    document.review_status = ReviewStatus.PENDING
    document.save(update_fields=["review_status", "updated_at"])


@transaction.atomic
def update_document(document_no: int, data: dict[str, Any]) -> None:
    document = _locked_document(document_no)
    _check_revision(document, data["revision"])
    for field in ("file_name", "document_type", "fk_batch_no"):
        setattr(document, field, data[field])
    document.review_status = ReviewStatus.PENDING
    document.save(update_fields=["file_name", "document_type", "fk_batch_no", "review_status", "updated_at"])
    logger.info("document=%s metadata updated", document_no)


@transaction.atomic
def set_review(document_no: int, status: str) -> None:
    document = _locked_document(document_no)
    document.review_status = status
    document.save(update_fields=["review_status", "updated_at"])
    logger.info("document=%s review=%s", document_no, status)


@transaction.atomic
def set_accuracy(document_no: int, log_no: int, model: LogModel, accurate: bool) -> None:
    document = _locked_document(document_no)
    log = get_extraction(document_no, log_no, model)
    if accurate and not (log.markdown_text or "").strip():
        raise ValidationError("An empty extraction cannot be marked accurate.")
    if log.user_selected_accurate != accurate:
        log.user_selected_accurate = accurate
        log.save(update_fields=["user_selected_accurate", "updated_at"])
        _pending(document)
    logger.info("document=%s %s=%s accurate=%s", document_no, model.__name__, log_no, accurate)


@transaction.atomic
def save_markdown(document_no: int, data: dict[str, Any], model: LogModel = DocExtractionLog,
                  log_no: int | None = None) -> DocExtractionLog | LLMExtractionLog:
    document = _locked_document(document_no)
    log: DocExtractionLog | LLMExtractionLog
    if log_no is None:
        # Manual content is a text extraction; provider runs are created by OCR.
        log = DocExtractionLog.objects.create(fk_document_no=document, markdown_text=data["markdown_text"])
        _pending(document)
    else:
        log = get_extraction(document_no, log_no, model)
        _check_revision(log, data["revision"])
        if log.markdown_text != data["markdown_text"]:
            log.markdown_text = data["markdown_text"]
            log.user_selected_accurate = False
            log.save(update_fields=["markdown_text", "user_selected_accurate", "updated_at"])
            _pending(document)
    logger.info("document=%s %s=%s Markdown saved", document_no, type(log).__name__, log.pk)
    return log


@transaction.atomic
def delete_record(document_no: int, model: LogModel | None = None, log_no: int | None = None) -> None:
    document = _locked_document(document_no)
    if model is None:
        # Delete related logs through Django's CASCADE; keep the original on disk.
        document.delete()
        logger.info("document=%s deleted with related logs; original retained", document_no)
    else:
        log = get_extraction(document_no, log_no, model)
        log.delete()
        _pending(document)
        logger.info("document=%s %s=%s deleted", document_no, model.__name__, log_no)

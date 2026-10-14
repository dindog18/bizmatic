"""Persist concurrent upload and re-run attempts through one extraction flow."""

import logging
from pathlib import Path

from asgiref.sync import async_to_sync, sync_to_async
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from ..models import Batch, Document, DocExtractionLog, LLMExtractionLog, ProcessingStatus, ReviewStatus, LLMRunStatus
from ..schemas.files import LLMExtractionResult, StoredFileMetadata, TextExtractedFile
from ..util import main_document_file_text_extraction
from ..utils.file_types import identify_file_type_metadata
from .llm import get_llm_provider, get_provider_model

logger = logging.getLogger(__name__)


def process_document_upload(files: list[UploadedFile]) -> Batch:
    """Allocate a batch, extract its files, and retain successful/failed attempts."""
    logger.info("upload received files=%s", len(files))
    if not files:
        raise ValueError("At least one uploaded file is required.")
    batch = Batch.objects.create()
    logger.info("batch=%s created", batch.batch_no)
    _process_extraction(batch, files)
    return batch


def process_document_rerun(document_no: int) -> None:
    """Re-extract the saved original with current provider settings."""
    document = get_object_or_404(Document.objects.select_related("fk_batch_no"), pk=document_no)
    _process_extraction(document.fk_batch_no, [], [document])


def process_batch_rerun(batch_no: int) -> None:
    """Re-extract every document currently in the existing batch."""
    batch = get_object_or_404(Batch, pk=batch_no)
    _process_extraction(batch, [], list(Document.objects.filter(fk_batch_no=batch).order_by("pk")))


def _stored_metadata(document: Document) -> StoredFileMetadata:
    path = Path(document.storage_path)
    try:
        # Check every original before changing statuses or creating new attempts.
        with path.open("rb") as original:
            original.read(1)
        size = path.stat().st_size
    except OSError as error:
        raise ValidationError(f"Original file for document #{document.pk} is unavailable.") from error
    return StoredFileMetadata(
        original_file_name=document.file_name, stored_file_name=path.name,
        storage_path=document.storage_path, mime_type=document.mime_type, file_size=size,
    )


def _process_extraction(batch: Batch | None, files: list[UploadedFile],
                        existing_documents: list[Document] | None = None) -> None:
    """Shared registration, extraction callbacks and failure handling for all runs."""
    batch_no = batch.pk if batch else 0
    stored_files = None
    existing: dict[str, Document] = {}
    if existing_documents is not None:
        if not existing_documents:
            raise ValidationError("This batch has no documents to re-run.")
        existing = {document.storage_path: document for document in existing_documents}
        if len(existing) != len(existing_documents):
            raise ValidationError("Documents sharing a storage path cannot be re-run together.")
        stored_files = [_stored_metadata(document) for document in existing_documents]
    documents: dict[str, Document] = {}
    text_logs: dict[str, DocExtractionLog] = {}
    llm_logs: dict[tuple[str, str], LLMExtractionLog] = {}
    registered = False
    logger.info("batch=%s %s started", batch_no, "re-run" if existing_documents is not None else "upload")

    def register(metadata: list[StoredFileMetadata]) -> None:
        nonlocal registered
        # Resolve configuration first; invalid settings must not leave active rows.
        providers = {provider: get_provider_model(provider) for provider in get_llm_provider().split(",")} if any(
            identify_file_type_metadata(file) == "image" for file in metadata
        ) else {}
        with transaction.atomic():
            for file in metadata:
                kind = identify_file_type_metadata(file)
                if existing_documents is None:
                    document = Document.objects.create(
                        fk_batch_no=batch, file_name=file.original_file_name,
                        mime_type=file.mime_type, document_type=kind, storage_path=file.storage_path,
                        processing_status=ProcessingStatus.PROCESSING,
                    )
                else:
                    document = existing[file.storage_path]
                    # Conditional update also prevents overlapping runs on the same record.
                    claimed = Document.objects.filter(pk=document.pk, updated_at=document.updated_at).exclude(
                        processing_status__in=[ProcessingStatus.QUEUED, ProcessingStatus.PROCESSING],
                    ).update(processing_status=ProcessingStatus.PROCESSING,
                             review_status=ReviewStatus.PENDING, updated_at=timezone.now())
                    if not claimed:
                        raise ValidationError(f"Document #{document.pk} is processing or changed. Reload before re-running.", code="conflict")
                documents[file.storage_path] = document
                if kind == "image":
                    for provider, model in providers.items():
                        llm_logs[file.storage_path, provider] = LLMExtractionLog.objects.create(
                            fk_document_no=document, provider=provider,
                            model_name=model, status=LLMRunStatus.QUEUED,
                        )
                else:
                    text_logs[file.storage_path] = DocExtractionLog.objects.create(fk_document_no=document)
        registered = True
        logger.info("batch=%s document metadata and new logs saved documents=%s", batch_no, len(metadata))

    def save_llm(file: StoredFileMetadata, result: LLMExtractionResult) -> None:
        # Save this attempt by ID; previous attempts remain intact.
        log = llm_logs[file.storage_path, result.provider]
        for field, value in result.model_dump().items():
            setattr(log, field, value)
        log.save()
        logger.info("batch=%s document=%s provider=%s model=%s log=%s saved status=%s input_tokens=%s output_tokens=%s duration_ms=%s", batch_no, documents[file.storage_path].pk, result.provider, result.model_name, log.pk, result.status, result.input_tokens, result.output_tokens, result.processing_time_ms)

    def save_result(file: StoredFileMetadata, result: TextExtractedFile | None, error: str | None) -> None:
        document = documents[file.storage_path]
        with transaction.atomic():
            if file.storage_path in text_logs:
                log = text_logs[file.storage_path]
                log.markdown_text = result.doc_markdown_text if result is not None else None
                log.error_message = error
                log.save()
            document.processing_status = ProcessingStatus.FAILED if error is not None else ProcessingStatus.COMPLETED
            document.save(update_fields=["processing_status", "updated_at"])
        logger.info("batch=%s document=%s file=%r result saved status=%s", batch_no, document.pk, file.original_file_name, document.processing_status)

    async def on_stored(metadata: list[StoredFileMetadata]) -> None:
        await sync_to_async(register, thread_sensitive=True)(metadata)

    async def on_result(file: StoredFileMetadata, result: TextExtractedFile | None, error: str | None) -> None:
        await sync_to_async(save_result, thread_sensitive=True)(file, result, error)

    async def on_llm_result(file: StoredFileMetadata, result: LLMExtractionResult) -> None:
        await sync_to_async(save_llm, thread_sensitive=True)(file, result)

    try:
        async_to_sync(main_document_file_text_extraction)(
            batch_no, files, stored_files=stored_files, on_stored=on_stored,
            on_result=on_result, on_llm_result=on_llm_result,
        )
    except Exception as extraction_error:
        logger.exception("batch=%s extraction failed", batch_no)
        if registered:
            # Only unfinished rows from this run change; historical logs are preserved.
            now = timezone.now()
            message = f"Extraction did not complete: {str(extraction_error) or type(extraction_error).__name__}"
            with transaction.atomic():
                unfinished = Document.objects.filter(pk__in=[doc.pk for doc in documents.values()], processing_status=ProcessingStatus.PROCESSING)
                LLMExtractionLog.objects.filter(pk__in=[log.pk for log in llm_logs.values()], status__in=[LLMRunStatus.QUEUED, LLMRunStatus.PROCESSING]).update(
                    status=LLMRunStatus.FAILED, error_message=message, updated_at=now,
                )
                DocExtractionLog.objects.filter(pk__in=[log.pk for log in text_logs.values()], markdown_text__isnull=True, error_message__isnull=True).update(
                    error_message=message, updated_at=now,
                )
                unfinished.update(processing_status=ProcessingStatus.FAILED, updated_at=now)
            logger.warning("batch=%s failure records saved", batch_no)
        raise
    finally:
        if batch is not None and registered:
            batch.save(update_fields=["updated_at"])
    logger.info("batch=%s extraction completed documents=%s", batch_no, len(documents))

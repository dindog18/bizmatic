"""Backward-compatible exports for document extraction helpers."""
import asyncio
import logging
from collections.abc import Awaitable, Callable
from time import perf_counter

from django.core.files.uploadedfile import UploadedFile

from .schemas.files import FileType, LLMExtractionResult, StoredFileMetadata, TextExtractedFile
from .services.documents import (
    document_file_text_extraction,
)
from .services.images import image_file_ocr_text_extraction
from .services.llm import get_concurrency_limit
from .services.storage import store_files_in_hdd
from .utils.concurrency import concurrent_map
from .utils.file_types import identify_file_type_metadata

logger = logging.getLogger(__name__)

# Main Document Text Extraction
async def main_document_file_text_extraction(
    batch_no: int, files: list[UploadedFile], *,
    stored_files: list[StoredFileMetadata] | None = None,
    on_stored: Callable[[list[StoredFileMetadata]], Awaitable[None]] | None = None,
    on_result: Callable[[StoredFileMetadata, TextExtractedFile | None, str | None], Awaitable[None]] | None = None,
    on_llm_result: Callable[[StoredFileMetadata, LLMExtractionResult], Awaitable[None]] | None = None,
) -> list[TextExtractedFile]:
    """Extract concurrently; re-runs can reuse already stored files."""
    started = perf_counter()
    logger.info("batch=%s extraction started files=%s", batch_no, len(stored_files) if stored_files is not None else len(files))
    limit = get_concurrency_limit()
    logger.info("batch=%s concurrency limit=%s", batch_no, limit)
    # Share one provider limit across all images in this batch.
    provider_semaphore = asyncio.Semaphore(limit)
    try:
        list_of_stored_files = stored_files if stored_files is not None else await store_files_in_hdd(batch_no, files, max_concurrency=limit)
        if on_stored is not None:
            logger.info("batch=%s registering stored file metadata", batch_no)
            await on_stored(list_of_stored_files)
    except Exception:
        logger.exception("batch=%s storage or metadata registration failed", batch_no)
        raise

    completed = 0

    async def extract_file(stored_file: StoredFileMetadata) -> TextExtractedFile:
        file_type: FileType = identify_file_type_metadata(stored_file)
        logger.info("batch=%s file=%r extraction started type=%s", batch_no, stored_file.original_file_name, file_type)

        if file_type == "image":
            async def save_llm(result: LLMExtractionResult) -> None:
                if on_llm_result is not None:
                    await on_llm_result(stored_file, result)

            image_markdown_text: dict[str, str] = await image_file_ocr_text_extraction(
                stored_file, semaphore=provider_semaphore,
                on_result=save_llm if on_llm_result is not None else None,
            )
            extracted_file_data = TextExtractedFile(
                image_markdown_text=image_markdown_text,
                doc_markdown_text=None,
                extracted_text_metadata=stored_file,
            )
        else:
            doc_markdown_text: str = await document_file_text_extraction(stored_file)
            extracted_file_data = TextExtractedFile(
                image_markdown_text=None,
                doc_markdown_text=doc_markdown_text,
                extracted_text_metadata=stored_file,
            )
        return extracted_file_data

    async def extract(stored_file: StoredFileMetadata) -> TextExtractedFile:
        nonlocal completed
        file_started = perf_counter()
        try:
            result = await extract_file(stored_file)
            if on_result is not None:
                await on_result(stored_file, result, None)
        except asyncio.CancelledError:
            logger.warning("batch=%s file=%r extraction cancelled", batch_no, stored_file.original_file_name)
            raise
        except Exception as error:
            logger.exception("batch=%s file=%r extraction or result save failed", batch_no, stored_file.original_file_name)
            if on_result is not None:
                await on_result(stored_file, None, str(error))
            raise
        completed += 1
        logger.info("batch=%s file=%r completed progress=%s/%s duration_ms=%s", batch_no, stored_file.original_file_name, completed, len(list_of_stored_files), round((perf_counter() - file_started) * 1000))
        return result

    results = await concurrent_map(extract, list_of_stored_files, limit)
    logger.info("batch=%s extraction completed files=%s duration_ms=%s", batch_no, len(results), round((perf_counter() - started) * 1000))
    return results

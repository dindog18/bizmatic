import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from time import perf_counter

from pydantic import TypeAdapter

from ..schemas.files import LLMExtractionResult, StoredFileMetadata
from ..utils.concurrency import concurrent_map

logger = logging.getLogger(__name__)


async def image_file_ocr_text_extraction(
    stored_file: StoredFileMetadata, *, semaphore: asyncio.Semaphore | None = None,
    on_result: Callable[[LLMExtractionResult], Awaitable[None]] | None = None,
) -> dict[str, str]:
    """Return ``{provider: raw_text}`` for every configured OCR/VLM provider.

    Invalid metadata and provider errors are raised to the caller; this
    function does not silently skip providers or fall back to another one.

    Output of dict is LLM and the Markdown_text
    """
    from .llm import extract_with_llm, extract_with_llm_result, get_concurrency_limit, get_file_mime_type, get_llm_provider, get_provider_model

    # Validate stored metadata strictly before passing values to providers.
    adapter = TypeAdapter(str)
    file_path = adapter.validate_python(stored_file.storage_path, strict=True)
    mime_type = adapter.validate_python(
        get_file_mime_type(file_path) if stored_file.mime_type is None else stored_file.mime_type,
        strict=True,
    )
    # Resolve missing or generic MIME types from the stored file itself.
    if not mime_type or mime_type == "application/octet-stream":
        mime_type = get_file_mime_type(file_path)
    if not mime_type.startswith("image/"):
        raise ValueError(f"Expected an image file, got {mime_type}.")
    if not Path(file_path).is_file():
        raise FileNotFoundError(file_path)

    # Run configured providers together, bounded across images by the shared limit.
    providers = get_llm_provider().split(",")
    logger.info("batch=%s file=%r image extraction providers=%s", Path(file_path).parent.name, stored_file.original_file_name, ",".join(providers))

    async def call_provider(provider: str) -> str:
        if on_result is None:
            return await extract_with_llm(provider, file_path, mime_type)
        started = perf_counter()
        try:
            result = await extract_with_llm_result(provider, file_path, mime_type)
        except Exception as error:
            await on_result(LLMExtractionResult(
                provider=provider, model_name=get_provider_model(provider), status="failed",
                error_message=str(error), processing_time_ms=round((perf_counter() - started) * 1000),
            ))
            raise
        await on_result(result)
        return result.markdown_text or ""

    async def extract(provider: str) -> str:
        started = perf_counter()
        logger.info("batch=%s file=%r provider=%s started", Path(file_path).parent.name, stored_file.original_file_name, provider)
        try:
            text = await call_provider(provider)
        except asyncio.CancelledError:
            logger.warning("batch=%s file=%r provider=%s cancelled", Path(file_path).parent.name, stored_file.original_file_name, provider)
            raise
        except Exception as error:
            logger.error("batch=%s file=%r provider=%s failed error=%s", Path(file_path).parent.name, stored_file.original_file_name, provider, error, exc_info=True)
            raise
        logger.info("batch=%s file=%r provider=%s completed duration_ms=%s", Path(file_path).parent.name, stored_file.original_file_name, provider, round((perf_counter() - started) * 1000))
        return text

    texts = await concurrent_map(extract, providers, get_concurrency_limit(), semaphore=semaphore)
    results = dict(zip(providers, texts, strict=True))
    return TypeAdapter(dict[str, str]).validate_python(results, strict=True)

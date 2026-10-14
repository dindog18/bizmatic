import asyncio
import logging
import uuid
from pathlib import Path
from typing import cast

from django.core.files.uploadedfile import UploadedFile

from bizmatic_django.environment import get_env

from ..schemas.files import StoredFileMetadata
from ..utils.concurrency import concurrent_map

logger = logging.getLogger(__name__)


# Store uploaded files on disk using the path configured in the environment.
async def store_files_in_hdd(
    batch_no: int,
    files: list[UploadedFile],
    *,
    max_concurrency: int | None = None,
) -> list[StoredFileMetadata]:
    """Upload files into a batch folder and return their stored metadata.

    ``batch_no`` determines the subdirectory under ``LOCAL_FILE_STORAGE_PATH``.
    Each stored name is prefixed with a UUID so files with the same original
    name do not overwrite one another.
    """
    # Get storage path from .env and validate configuration.
    logger.info("batch=%s storage started files=%s", batch_no, len(files))
    local_file_storage_path = get_env("LOCAL_FILE_STORAGE_PATH")
    if not local_file_storage_path:
        raise ValueError("LOCAL_FILE_STORAGE_PATH is not configured.")

    from .llm import get_concurrency_limit, get_file_mime_type

    limit = get_concurrency_limit() if max_concurrency is None else max_concurrency
    # Disk writes run in worker threads so they do not block the event loop.
    storage_path = Path(local_file_storage_path) / str(batch_no)
    await asyncio.to_thread(storage_path.mkdir, parents=True, exist_ok=True)

    def store(uploaded_file: UploadedFile) -> StoredFileMetadata:
        if uploaded_file.name is None:
            raise ValueError("Uploaded file must have a file name.")
        if uploaded_file.size is None:
            raise ValueError("Uploaded file size is unavailable.")

        # Keep only the file name, not any client-supplied directory path.
        original_name = Path(uploaded_file.name).name
        unique_name = f"{uuid.uuid4()}_{original_name}"
        file_path = storage_path / unique_name
        # Django uploads may be chunked, so write each chunk to disk.
        with open(file_path, "wb+") as destination:
            for chunk in uploaded_file.chunks():
                destination.write(chunk)

        # Record the original name and the unique on-disk location.
        return StoredFileMetadata(
            original_file_name=original_name,
            stored_file_name=unique_name,
            storage_path=str(file_path),
            mime_type=(get_file_mime_type(str(file_path)) if not uploaded_file.content_type or uploaded_file.content_type == "application/octet-stream" else uploaded_file.content_type),
            file_size=cast(int, uploaded_file.size),
        )

    async def store_async(uploaded_file: UploadedFile) -> StoredFileMetadata:
        logger.info("batch=%s file=%r storage started", batch_no, uploaded_file.name)
        try:
            metadata = await asyncio.to_thread(store, uploaded_file)
        except Exception:
            logger.exception("batch=%s file=%r storage failed", batch_no, uploaded_file.name)
            raise
        logger.info("batch=%s file=%r stored bytes=%s", batch_no, metadata.original_file_name, metadata.file_size)
        return metadata

    stored_files = await concurrent_map(store_async, files, limit)
    logger.info("batch=%s storage completed files=%s", batch_no, len(stored_files))
    return stored_files

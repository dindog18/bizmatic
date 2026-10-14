from typing import Literal

from pydantic import BaseModel, Field


class StoredFileMetadata(BaseModel):
    """Metadata for a file copied into local storage.

    The original name and MIME type support classification, while the stored
    name, path, and size describe the saved file.
    """

    original_file_name: str = Field(min_length=1, max_length=255)
    stored_file_name: str
    storage_path: str = Field(min_length=1, max_length=1000)
    mime_type: str | None = Field(max_length=150)
    file_size: int = Field(ge=0)


class LLMExtractionResult(BaseModel):
    """Provider output and measured metadata used to save extraction logs."""
    provider: str = Field(min_length=1, max_length=100)
    model_name: str = Field(min_length=1, max_length=150)
    status: Literal["completed", "failed"]
    markdown_text: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    processing_time_ms: int = Field(ge=0)
    error_message: str | None = None

class TextExtractedFile(BaseModel):
    """Text extracted file from local storage."""
    image_markdown_text: dict[str, str] | None
    doc_markdown_text: str | None
    extracted_text_metadata: StoredFileMetadata

# General file categories used by the upload classifier and extraction router.
FileType = Literal["image", "pdf", "word", "excel", "text", "unknown"]

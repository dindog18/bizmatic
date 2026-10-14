from pathlib import Path

from django.core.files.uploadedfile import UploadedFile

from ..schemas.files import FileType, StoredFileMetadata


def identify_file_type_upload_file(uploaded_file: UploadedFile) -> FileType:
    """Identify an uploaded file using its MIME type and extension.

    This is a backup classifier for files before they have been stored.
    """
    if uploaded_file.name is None:
        raise ValueError("Uploaded file must have a file name.")
    extension = Path(uploaded_file.name).suffix.lower()
    mime_type = uploaded_file.content_type or ""
    # MIME type is the strongest signal for images; other types use extensions.
    if mime_type.startswith("image/"):
        return "image"
    if mime_type == "application/pdf" or extension == ".pdf":
        return "pdf"
    if extension in {".doc", ".docx"}:
        return "word"
    if extension in {".xls", ".xlsx"}:
        return "excel"
    if extension in {".txt", ".csv"}:
        return "text"
    return "unknown"


def identify_file_type_metadata(file: StoredFileMetadata) -> FileType:
    """Identify a stored file using metadata.

    MIME type is preferred when available, while the original file extension
    is used as a fallback.
    """
    name = file.original_file_name or file.stored_file_name or file.storage_path
    extension = Path(name).suffix.lower()
    mime_type = (file.mime_type or "").lower()
    if mime_type.startswith("image/"):
        return "image"
    if mime_type == "application/pdf" or extension == ".pdf":
        return "pdf"
    if mime_type in {
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    } or extension in {".doc", ".docx"}:
        return "word"
    if mime_type in {
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    } or extension in {".xls", ".xlsx"}:
        return "excel"
    if mime_type.startswith("text/") or extension in {".txt", ".csv"}:
        return "text"
    return "unknown"

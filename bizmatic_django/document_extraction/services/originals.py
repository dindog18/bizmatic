"""Read a document's original from its saved storage path."""

import mimetypes
from pathlib import Path

from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404

from ..models import Document


def original_file_response(document_no: int, *, download: bool = False) -> FileResponse:
    # Accept a document ID, never a file path supplied by the browser.
    document = get_object_or_404(Document, pk=document_no)
    try:
        original = Path(document.storage_path).open("rb")
    except (OSError, ValueError) as error:
        raise Http404("The original file is no longer available.") from error
    mime_type = mimetypes.guess_type(document.file_name)[0] or "application/octet-stream"
    response = FileResponse(original, content_type=mime_type,
                            filename=Path(document.file_name).name, as_attachment=download)
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    response["Cache-Control"] = "private, no-store"
    return response

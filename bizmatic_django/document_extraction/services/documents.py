import asyncio
from pathlib import Path

import pandas as pd
import pymupdf
from docx import Document

from ..schemas.files import FileType, StoredFileMetadata
from ..utils.file_types import identify_file_type_metadata
from ..utils.markdown import markdown_table


async def document_file_text_extraction(stored_file: StoredFileMetadata) -> str:
    """Extract a supported document and return its contents as Markdown.

    Images are intentionally handled by the separate image OCR pipeline.
    """
    file_type: FileType = identify_file_type_metadata(stored_file)
    # Images should go through image_file_ocr_text_extraction instead.
    if file_type == "image":
        raise ValueError("Expected a document file, not an image file.")
    if file_type == "unknown":
        raise ValueError(f"Unsupported or unknown file type: {stored_file.original_file_name}")

    file_path = Path(stored_file.storage_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Stored file does not exist: {file_path}")

    # Keep each format implementation separate while sharing dispatch here.
    extractors = {
        "pdf": extract_pdf_to_markdown,
        "word": extract_word_to_markdown,
        "excel": extract_excel_to_markdown,
        "text": extract_text_to_markdown,
    }
    extractor = extractors.get(file_type)
    if extractor is None:
        raise ValueError(f"Unsupported document file type: {file_type}")
    return await asyncio.to_thread(extractor, file_path)


def extract_pdf_to_markdown(file_path: Path) -> str:
    """Extract text from a text-based PDF and label each page in Markdown.

    Scanned or image-only PDFs may contain little or no extractable text and
    should be routed through OCR when that workflow is added.
    """
    parts = []
    with pymupdf.open(file_path) as pdf:
        for page_number, page in enumerate(pdf, start=1):
            parts.append(f"## Page {page_number}\n\n{page.get_text('text').strip()}")
    return "\n\n".join(parts).strip()


def extract_word_to_markdown(file_path: Path) -> str:
    """Convert a .docx file to basic Markdown, including headings and tables."""
    if file_path.suffix.lower() == ".doc":
        raise ValueError("Legacy .doc files are not directly supported. Convert the file to .docx first.")
    document = Document(str(file_path))
    parts = []
    # Preserve heading hierarchy and regular paragraph text.
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style = paragraph.style
        style_name = (style.name or "").lower() if style is not None else ""
        if style_name.startswith("heading"):
            try:
                level = int(style_name.split()[-1])
            except (ValueError, IndexError):
                level = 2
            parts.append(f"{'#' * min(max(level, 1), 6)} {text}")
        else:
            parts.append(text)
    # Append document tables after the paragraphs.
    for table in document.tables:
        rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
        if rows:
            parts.append(markdown_table(rows))
    return "\n\n".join(parts).strip()


def extract_excel_to_markdown(file_path: Path) -> str:
    """Convert each worksheet in an Excel workbook into a Markdown table."""
    workbook = pd.ExcelFile(file_path)
    parts = []
    for sheet_name in workbook.sheet_names:
        # Read values as strings and render missing cells as blanks.
        dataframe = pd.read_excel(workbook, sheet_name=sheet_name, dtype=str).fillna("")
        parts.append(f"## Sheet: {sheet_name}")
        parts.append("_Empty worksheet_" if dataframe.empty else dataframe.to_markdown(index=False))
    return "\n\n".join(parts).strip()


def extract_text_to_markdown(file_path: Path) -> str:
    """Convert TXT and CSV files to Markdown (CSV becomes a table)."""
    if file_path.suffix.lower() == ".csv":
        return extract_csv_to_markdown(file_path)
    return file_path.read_text(encoding="utf-8", errors="replace").strip()


def extract_csv_to_markdown(file_path: Path) -> str:
    """Convert a CSV file into a Markdown table."""
    # Read values as strings and render missing cells as blanks.
    # PyCharm cannot resolve pandas' generic Unpack overloads for this valid call.
    # noinspection PyArgumentList
    dataframe = pd.read_csv(str(file_path), dtype=str).fillna("")
    return "_Empty CSV file_" if dataframe.empty else dataframe.to_markdown(index=False)

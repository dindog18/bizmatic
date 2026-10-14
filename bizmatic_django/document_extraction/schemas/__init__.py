"""Pydantic schemas shared by the document extraction app."""

from .files import FileType, StoredFileMetadata

__all__ = ["FileType", "StoredFileMetadata"]

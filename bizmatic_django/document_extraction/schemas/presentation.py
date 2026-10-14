"""Typed display data for templates, without modifying database models."""

from dataclasses import dataclass
from typing import Any

from django.db.models import Model


@dataclass(frozen=True)
class RecordDisplay:
    record: Model

    def __getattr__(self, name: str) -> Any:
        # Preserve access to saved fields such as pk, timestamps and foreign keys.
        return getattr(self.record, name)


@dataclass(frozen=True)
class DocumentDisplay(RecordDisplay):
    processing_label: str
    processing_color: str
    review_label: str
    review_color: str
    extension: str
    icon: str
    color: str


@dataclass(frozen=True)
class LogDisplay(RecordDisplay):
    log_no: int
    status_label: str = ""
    color: str = "secondary"
    detail_route: str = ""
    edit_route: str = ""
    accuracy_route: str = ""
    delete_route: str = ""


@dataclass(frozen=True)
class BatchDisplay(RecordDisplay):
    count: int
    completed: int
    failed: int

    @property
    def progress(self) -> int:
        return round(self.completed / self.count * 100) if self.count else 0

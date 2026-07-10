import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ExtractionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    data: dict
    raw_text: str | None
    error: str | None
    created_at: datetime


class DocumentFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_filename: str
    content_type: str
    file_size: int
    page_order: int
    created_at: datetime


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    application_id: uuid.UUID | None
    doc_type: str
    status: str
    created_at: datetime
    updated_at: datetime
    files: list[DocumentFileOut]
    extraction: ExtractionOut | None


class DocumentSummary(BaseModel):
    """Lightweight row for the list view."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    doc_type: str
    status: str
    file_count: int
    created_at: datetime
    updated_at: datetime

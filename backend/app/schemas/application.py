import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.document import DocumentOut


class ApplicationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_id: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class ApplicationDetail(BaseModel):
    """An application with its documents and the merged, fill-ready data."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_id: str | None
    status: str
    documents: list[DocumentOut]
    # Merged extraction view keyed by doc_type, e.g. {"passport": {...}, "g28": {...}}.
    # Loose passthrough — the fill-time LLM mapper reconciles keys to form fields.
    data: dict

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class FormFillRunCreate(BaseModel):
    case_id: str
    form_url: str


class FormFillField(BaseModel):
    selector: str
    label: str
    input_type: str
    options: list[str] | None = None


class FormFillRunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_id: str | None
    form_url: str
    status: str
    created_at: datetime
    updated_at: datetime


class FormFillRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_id: str | None
    form_url: str
    status: str
    fields: list[FormFillField]
    mapping: dict
    error: str | None
    created_at: datetime
    updated_at: datetime

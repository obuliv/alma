import enum
import uuid

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, uuid_pk


class FormFillRunStatus(str, enum.Enum):
    filling = "filling"
    filled = "filled"
    failed = "failed"


class FormFillRun(TimestampMixin, Base):
    """One browser-automation attempt to populate a target form for an Application.

    `fields` is the scraped form-control list, `mapping` is the
    `{selector: value}` actually applied — both JSON since neither is tied to a
    specific form.
    """

    __tablename__ = "form_fill_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    form_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default=FormFillRunStatus.filling.value, nullable=False
    )
    fields: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    mapping: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    application: Mapped["Application"] = relationship()  # noqa: F821

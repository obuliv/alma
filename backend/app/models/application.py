import enum
import uuid

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, uuid_pk


class ApplicationStatus(str, enum.Enum):
    new = "new"
    ready = "ready"
    submitting = "submitting"
    submitted = "submitted"
    failed = "failed"


class Application(TimestampMixin, Base):
    """Groups the documents (passport + G-28) that feed one form-fill run."""

    __tablename__ = "applications"

    id: Mapped[uuid.UUID] = uuid_pk()
    # Human-entered identifier used to group a passport + G-28 at upload time and
    # to select which application's data to use at form-fill time.
    case_id: Mapped[str | None] = mapped_column(
        String(128), unique=True, index=True, nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(32), default=ApplicationStatus.new.value, nullable=False
    )
    form_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    documents: Mapped[list["Document"]] = relationship(  # noqa: F821
        back_populates="application"
    )

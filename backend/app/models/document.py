import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, uuid_pk


class DocType(str, enum.Enum):
    passport = "passport"
    g28 = "g28"


class DocumentStatus(str, enum.Enum):
    uploaded = "uploaded"
    extracting = "extracting"
    extracted = "extracted"
    failed = "failed"
    flagged = "flagged"


class Document(TimestampMixin, Base):
    """A logical document (one passport, one G-28) that may span many files/pages."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"), nullable=True
    )
    doc_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default=DocumentStatus.uploaded.value, nullable=False
    )

    application: Mapped["Application | None"] = relationship(  # noqa: F821
        back_populates="documents"
    )
    files: Mapped[list["DocumentFile"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentFile.page_order",
    )
    extraction: Mapped["ExtractionResult | None"] = relationship(  # noqa: F821
        back_populates="document",
        cascade="all, delete-orphan",
        uselist=False,
    )


class DocumentFile(Base):
    """One uploaded file/page belonging to a Document."""

    __tablename__ = "document_files"

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    page_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped["Document"] = relationship(back_populates="files")

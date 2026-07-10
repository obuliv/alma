import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import uuid_pk


class ExtractionResult(Base):
    """Structured data extracted from a Document (one row per document).

    `data` is JSON so step 2 (real extraction) can evolve the field set
    without a migration.
    """

    __tablename__ = "extraction_results"

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Field-level fixes the sanity-check pass auto-applied to `data`, e.g.
    # [{"field": ..., "before": ..., "after": ..., "reason": ...}]. `data`
    # already reflects these; kept separately so a flagged document still
    # shows what changed rather than silently overwriting the raw LLM read.
    corrections: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped["Document"] = relationship(  # noqa: F821
        back_populates="extraction"
    )

"""Extraction service — STUB (step 2 lands the real OCR/LLM logic here).

The upload flow already drives status transitions and persists an
ExtractionResult, so step 2 only needs to replace `_extract` with real logic
that reads a document's files and returns structured `data`.
"""
import uuid

from sqlalchemy.orm import Session

from app.models import Document, DocumentStatus, ExtractionResult

# Fields step 2 is expected to populate. Kept here as documentation of the
# target schema; the placeholder emits empty strings so the UI can render it.
EXPECTED_FIELDS = (
    "full_name",
    "date_of_birth",
    "country",
    "passport_number",
    "address",
    "attorney_name",
    "firm",
)


class ExtractionService:
    def run(self, db: Session, document_id: uuid.UUID) -> None:
        """Extract structured data for a document and persist the result.

        Marks the document `extracting`, then `extracted`/`failed`.
        """
        document = db.get(Document, document_id)
        if document is None:
            return

        document.status = DocumentStatus.extracting.value
        db.commit()

        try:
            data, raw_text = self._extract(db, document)
        except Exception as exc:  # noqa: BLE001 - stub records any failure
            self._store(db, document, data={}, raw_text=None, error=str(exc))
            document.status = DocumentStatus.failed.value
            db.commit()
            return

        self._store(db, document, data=data, raw_text=raw_text, error=None)
        document.status = DocumentStatus.extracted.value
        db.commit()

    def _extract(self, db: Session, document: Document) -> tuple[dict, str | None]:
        """STUB: return placeholder fields. Replace with OCR/LLM in step 2."""
        return {field: "" for field in EXPECTED_FIELDS}, None

    def _store(
        self,
        db: Session,
        document: Document,
        *,
        data: dict,
        raw_text: str | None,
        error: str | None,
    ) -> None:
        result = document.extraction
        if result is None:
            result = ExtractionResult(document_id=document.id)
            db.add(result)
        result.data = data
        result.raw_text = raw_text
        result.error = error


extraction_service = ExtractionService()

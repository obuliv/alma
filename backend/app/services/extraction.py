"""Extraction service — STUB (step 2 lands the real OCR/LLM logic here).

The upload flow already drives status transitions and persists an
ExtractionResult, so step 2 only needs to replace `_extract` with real logic
that reads a document's files and returns a `data` dict.

Form-agnostic by design: extraction returns **whatever keys the LLM finds** in
the document — there is no fixed field list. The fill-time mapper (stream 3)
takes these keys and the target form's field keys and generates the mapping, so
neither side is tied to a specific form or schema.

Wiring for stream 2 is in place: read a document's files via
`app.services.storage.read_file`, pass them as attachments to
`get_llm_client().complete_json(...)`, and return the parsed dict.
"""
import uuid

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import Document, DocumentStatus, ExtractionResult

logger = get_logger(__name__)


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
        """STUB: return an empty dict. Replace with OCR/LLM in step 2.

        Stream 2 replaces this body with, roughly:
            client = get_llm_client()
            attachments = [(storage.read_file(f.file_path), f.content_type)
                           for f in document.files]
            data = client.complete_json(system=<prompt for doc_type>,
                                        user="Extract all fields as JSON.",
                                        attachments=attachments)
        `data` keys are whatever the LLM returns — no fixed schema.
        """
        logger.info("extraction stub for document %s (%s)", document.id, document.doc_type)
        return {}, None

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

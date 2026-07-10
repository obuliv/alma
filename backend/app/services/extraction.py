"""Extraction service.

The upload flow drives status transitions and persists an ExtractionResult;
`_extract` reads a document's files and returns `(data, raw_text)`.

Form-agnostic by design: extraction returns **whatever keys the LLM finds** in
the document — there is no fixed field list. The fill-time mapper (stream 3)
takes these keys and the target form's field keys and generates the mapping, so
neither side is tied to a specific form or schema.

Pipeline, per document, uniform regardless of `settings.ocr_mode`:
1. Reduce every file to text: a PDF's embedded text layer if it has one
   (`app.services.text_extraction`), otherwise the configured OCR engine
   (`app.services.ocr.get_ocr_engine()`) on the rasterized/raw page images.
2. Concatenate into `raw_text`, then one `complete_json` call turns it into
   the flat key/value `data` dict.
"""
import uuid

from sqlalchemy.orm import Session

from app.core.errors import ExtractionError
from app.core.logging import get_logger
from app.models import Document, DocumentStatus, ExtractionResult
from app.services import storage, text_extraction
from app.services.llm import get_llm_client
from app.services.ocr import get_ocr_engine

logger = get_logger(__name__)

_PASSPORT_SYSTEM = (
    "You are extracting structured data from the transcribed text of a "
    "passport's biographic page. Return a single flat JSON object with every "
    "field you can identify, using clear snake_case keys — for example "
    "surname, given_names, passport_number, nationality, date_of_birth, sex, "
    "place_of_birth, date_of_issue, date_of_expiry, issuing_authority. "
    "Include any additional fields present in the text even if not listed "
    "here. Omit fields you cannot find; do not guess or hallucinate values."
)

_G28_SYSTEM = (
    "You are extracting structured data from the transcribed text of a "
    "USCIS Form G-28 (Notice of Entry of Appearance as Attorney). Return a "
    "single flat JSON object with every field you can identify, using clear "
    "snake_case keys — for example attorney_name, attorney_bar_number, "
    "law_firm_name, client_family_name, client_given_name, client_address, "
    "uscis_online_account_number, case_type. Include any additional fields "
    "present in the text even if not listed here. Omit fields you cannot "
    "find; do not guess or hallucinate values."
)

_SYSTEM_PROMPTS = {
    "passport": _PASSPORT_SYSTEM,
    "g28": _G28_SYSTEM,
}


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
        except Exception as exc:  # noqa: BLE001 - record any failure as `failed`
            self._store(db, document, data={}, raw_text=None, error=str(exc))
            document.status = DocumentStatus.failed.value
            db.commit()
            return

        self._store(db, document, data=data, raw_text=raw_text, error=None)
        document.status = DocumentStatus.extracted.value
        db.commit()

    def _extract(self, db: Session, document: Document) -> tuple[dict, str | None]:
        """Reduce every file to text, then turn the combined text into JSON."""
        page_texts = [self._file_to_text(f) for f in document.files]
        raw_text = "\n\n---\n\n".join(text for text in page_texts if text.strip())
        if not raw_text.strip():
            raise ExtractionError(
                f"No text could be extracted from document {document.id}"
            )

        try:
            system = _SYSTEM_PROMPTS[document.doc_type]
        except KeyError:
            raise ExtractionError(f"No extraction prompt for doc_type {document.doc_type!r}")
        client = get_llm_client()
        data = client.complete_json(system=system, user=raw_text)
        return data, raw_text

    def _file_to_text(self, file) -> str:
        """Text layer for a text-PDF; OCR engine output otherwise."""
        content = storage.read_file(file.file_path)
        if file.content_type == "application/pdf":
            text = text_extraction.pdf_text_layer(content)
            if text_extraction.has_text_layer(text):
                return text
            images = text_extraction.rasterize_pdf(content)
        else:
            images = [content]
        return get_ocr_engine().image_to_text(images)

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

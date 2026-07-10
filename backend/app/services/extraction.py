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
   For PDFs, filled AcroForm field values are always merged in too — a
   fillable PDF's answers live in form-field widgets, not the page's text
   stream, so the text layer alone sees only the blank template.
2. Concatenate into `raw_text`, then one `complete_json` call turns it into
   the flat key/value `data` dict.
"""
import json
import uuid

from sqlalchemy.orm import Session

from app.core.errors import ExtractionError, LLMError
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

# Appended to every doc-type prompt: `form_field_text` (text_extraction.py)
# renders each PDF checkbox/radio widget as a `name: true`/`name: false`
# line, checked or not, so this is a fixed, learnable convention rather than
# a per-document guess.
_FORM_FIELD_BOOLEAN_NOTE = (
    " The text may include a \"Form field values\" section. Lines there "
    "formatted as `field_name: true` or `field_name: false` are checkboxes "
    "or radio options — render these as JSON boolean values (true/false), "
    "not strings, keyed by a snake_case name derived from the field's "
    "context (nearby label text), not the raw field_name."
)

_PASSPORT_SYSTEM += _FORM_FIELD_BOOLEAN_NOTE
_G28_SYSTEM += _FORM_FIELD_BOOLEAN_NOTE

_SYSTEM_PROMPTS = {
    "passport": _PASSPORT_SYSTEM,
    "g28": _G28_SYSTEM,
}

# Doc-type / cross-document validation prompts below are given field *names*
# only, never values — they judge shape, not content, so no PII needs to
# leave the extracted-data boundary for these checks.

_DOC_TYPE_CHECK_SYSTEM = (
    "You validate whether a set of extracted field names is consistent with "
    "a claimed document type. You are given the document type and the field "
    "names (not values) extracted from it. Judge only whether those field "
    "names look like they belong to that type of document. Respond with a "
    'single JSON object: {"matches": true|false, "reason": "<one short '
    'sentence>"}.'
)

_IDENTITY_PAIR_SYSTEM = (
    "Two documents from the same case were extracted. You are given each "
    "document's type and its field names (not values). Identify field name "
    "pairs — one from each document — that are expected to hold the "
    "identical real-world identity value: the applicant/client/beneficiary's "
    "name, date of birth, or similar identifying detail. Do not pair an "
    "attorney's or preparer's name field against the applicant's. Match at "
    "the finest available granularity (e.g. a given-name field pairs with a "
    "given-name field, not with a combined full-name field). Only include "
    "pairs you are confident represent the same concept for the same "
    "person. Respond with a single JSON object: "
    '{"pairs": [{"field_a": "...", "field_b": "...", "concept": "..."}]}. '
    'If no such pairs exist, respond {"pairs": []}.'
)


def _normalize(value: str) -> str:
    return " ".join(value.strip().casefold().split())


class ExtractionService:
    def run(self, db: Session, document_id: uuid.UUID) -> None:
        """Extract structured data for a document and persist the result.

        Marks the document `extracting`, then `extracted`/`failed`/`flagged`.
        `flagged` means extraction itself succeeded but a validation check
        (doc-type match, or a cross-document identity conflict) raised a
        concern — distinct from `failed`, which means the pipeline broke.
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

        matches, reason = self._validate_doc_type(document.doc_type, data)
        if not matches:
            self._store(
                db,
                document,
                data=data,
                raw_text=raw_text,
                error=f"Uploaded file doesn't look like a {document.doc_type}: {reason}",
            )
            document.status = DocumentStatus.flagged.value
            db.commit()
            return

        self._store(db, document, data=data, raw_text=raw_text, error=None)
        document.status = DocumentStatus.extracted.value
        db.commit()

        self._check_conflicts(db, document)

    def _validate_doc_type(self, doc_type: str, data: dict) -> tuple[bool, str]:
        """Does the extracted field-name set look consistent with `doc_type`?

        Only field *names* are sent to the LLM, never values — this check
        doesn't need to see PII to judge whether the shape of what was found
        matches the claimed document type.
        """
        field_names = sorted(data.keys())
        if not field_names:
            return False, "no recognizable fields were extracted"

        client = get_llm_client()
        try:
            result = client.complete_json(
                system=_DOC_TYPE_CHECK_SYSTEM,
                user=f"Claimed document type: {doc_type}\nExtracted field names: {json.dumps(field_names)}",
            )
        except LLMError:
            # Fail open: an LLM hiccup on the validation step shouldn't sink
            # an otherwise-successful extraction.
            return True, ""
        return bool(result.get("matches", True)), str(result.get("reason", ""))

    def _check_conflicts(self, db: Session, document: Document) -> None:
        """Flag `document` and any sibling in the same application whose
        identity fields (name, DOB, ...) don't match."""
        application = document.application
        if application is None:
            return

        siblings = [
            sibling
            for sibling in application.documents
            if sibling.id != document.id
            and sibling.doc_type != document.doc_type
            and sibling.status == DocumentStatus.extracted.value
            and sibling.extraction
            and sibling.extraction.data
        ]
        for sibling in siblings:
            reason = self._compare_identity(document, sibling)
            if not reason:
                continue
            document.status = DocumentStatus.flagged.value
            document.extraction.error = (
                f"Possible identity conflict with {sibling.doc_type} document: {reason}"
            )
            sibling.status = DocumentStatus.flagged.value
            sibling.extraction.error = (
                f"Possible identity conflict with {document.doc_type} document: {reason}"
            )
            db.commit()

    def _compare_identity(self, doc_a: Document, doc_b: Document) -> str | None:
        """Ask the LLM which field *names* across the two documents should
        hold the same identity value, then compare the actual values
        ourselves. The LLM only ever sees field names, never values."""
        data_a, data_b = doc_a.extraction.data, doc_b.extraction.data
        field_names_a = sorted(data_a.keys())
        field_names_b = sorted(data_b.keys())

        client = get_llm_client()
        try:
            result = client.complete_json(
                system=_IDENTITY_PAIR_SYSTEM,
                user=(
                    f"Document A type: {doc_a.doc_type}\n"
                    f"Document A field names: {json.dumps(field_names_a)}\n\n"
                    f"Document B type: {doc_b.doc_type}\n"
                    f"Document B field names: {json.dumps(field_names_b)}"
                ),
            )
        except LLMError:
            return None

        mismatches = []
        for pair in result.get("pairs", []):
            field_a, field_b = pair.get("field_a"), pair.get("field_b")
            if field_a not in field_names_a or field_b not in field_names_b:
                continue  # guard against a hallucinated field name
            val_a, val_b = data_a.get(field_a), data_b.get(field_b)
            if val_a is None or val_b is None:
                continue
            if _normalize(str(val_a)) != _normalize(str(val_b)):
                mismatches.append(
                    f"{doc_a.doc_type}.{field_a}={val_a!r} vs {doc_b.doc_type}.{field_b}={val_b!r}"
                )
        return "; ".join(mismatches) if mismatches else None

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
        """Text layer (+ filled AcroForm fields) for a PDF; OCR otherwise."""
        content = storage.read_file(file.file_path)
        if file.content_type == "application/pdf":
            text = text_extraction.pdf_text_layer(content)
            if not text_extraction.has_text_layer(text):
                images = text_extraction.rasterize_pdf(content)
                text = get_ocr_engine().image_to_text(images)
            form_fields = text_extraction.form_field_text(content)
            if form_fields:
                text = f"{text}\n\nForm field values:\n{form_fields}"
            return text
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

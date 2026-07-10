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
from app.services.mrz import extract_mrz_fields
from app.services.ocr import get_ocr_engine

logger = get_logger(__name__)

_PASSPORT_SYSTEM = (
    "You are extracting structured data from the transcribed text of a "
    "passport's biographic page. Return a single flat JSON object with every "
    "field you can identify, using clear snake_case keys — for example "
    "surname, given_names, passport_number, nationality, date_of_birth, sex, "
    "place_of_birth, date_of_issue, date_of_expiry, issuing_authority. "
    "If the source document is not in English, render field values in "
    "English: proper nouns (personal names and place names) must be "
    "transliterated into Latin-alphabet characters — kept as the same "
    "real-world name or place, not swapped for a different English "
    "equivalent, just spelled out in Latin script if the original wasn't "
    "already; all other, descriptive or categorical values (e.g. sex/gender "
    "terms, document-type labels, issuing-authority names, place-name "
    "descriptors like \"City\" or \"Province\") should be translated to "
    "plain English. Put only the English/transliterated value in the JSON "
    "— do not include the original-language text alongside it. "
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
# a per-document guess. The "trust the label, not field_name" guidance
# below applies to *every* field in this section, not just booleans — some
# real-world PDFs have AcroForm field names that don't match what's actually
# printed at that field's position on the page (e.g. a field literally named
# `Line6_EMail[0]` can sit at the "Mobile Telephone Number" box), so the raw
# field_name alone isn't trustworthy as the source of a key's meaning.
_FORM_FIELD_BOOLEAN_NOTE = (
    " The text may include a \"Form field values\" section. Lines there "
    "formatted as `field_name: true` or `field_name: false` are checkboxes "
    "or radio options — render these as JSON boolean values (true/false), "
    "not strings. For every field in this section (boolean or not), derive "
    "the JSON key's meaning — and sanity-check the value itself — from "
    "nearby label text in the main transcribed text (the field's on-page "
    "context), not from the raw field_name; if the printed label and the "
    "raw field_name disagree about what the field is, trust the printed "
    "label."
)

# Normalizing dates here, rather than downstream at form-fill time, is
# deliberate: this is the only point in the pipeline where the LLM still has
# the whole document in front of it (issuing country, layout, other context)
# to resolve a numeric day/month ambiguity. By the time a value reaches the
# form-fill mapper it's a bare string under a key name — that context is
# gone, so it can only reformat, not disambiguate.
_DATE_NORMALIZATION_NOTE = (
    " Normalize every date value to ISO 8601 (\"YYYY-MM-DD\"), regardless of "
    "how it is printed in the source. When a numeric date is ambiguous "
    "between day-first and month-first (e.g. \"04/05/2025\"), resolve it "
    "using the issuing country/locale of this specific document — a "
    "US-issued document (USCIS forms, US passports) is month/day/year; "
    "most other countries' documents are day/month/year. A day value over "
    "12 is unambiguous either way. Prefer a textual month (e.g. "
    "\"29 APR 2025\") when present, since it removes the ambiguity "
    "entirely."
)

_PASSPORT_SYSTEM += _FORM_FIELD_BOOLEAN_NOTE + _DATE_NORMALIZATION_NOTE
_G28_SYSTEM += _FORM_FIELD_BOOLEAN_NOTE + _DATE_NORMALIZATION_NOTE

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

# Unlike the checks above, this one needs to see values — it's judging
# whether a value's apparent shape matches what its own field name implies
# (e.g. an email address under a "*_telephone_number" key), which can't be
# judged from names alone. It's the second line of defense against exactly
# the failure mode described in `_FORM_FIELD_BOOLEAN_NOTE`: a source PDF
# whose AcroForm field names don't match their printed position, so
# extraction ends up with values that are self-evidently the wrong kind of
# value for their key even after that prompt guidance.
_FIELD_VALUE_SANITY_SYSTEM = (
    "You review a set of extracted field name/value pairs from a document "
    "for internal consistency. For each field, judge whether its value's "
    "apparent type or format is consistent with what the field name "
    "implies — e.g. a field name suggesting an email address should hold "
    "something shaped like an email; a field name suggesting a "
    "phone/mobile/fax number should hold digits, not an email address; a "
    "field name suggesting a date should hold a date. Only report a "
    "mismatch you are confident about — a genuinely wrong-shaped value, not "
    "merely an unusual but plausible one — and never report a value of "
    "\"N/A\", empty, or similar placeholder, which is always fine. Respond "
    'with a single JSON object: {"issues": [{"field": "<field name>", '
    '"reason": "<one short sentence>"}]}. If nothing looks wrong, respond '
    '{"issues": []}.'
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
        (doc-type match, a field's value not matching what its name implies,
        or a cross-document identity conflict) raised a concern — distinct
        from `failed`, which means the pipeline broke.
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

        issues = self._validate_field_formats(data)
        error = self._format_issues(issues) if issues else None
        self._store(db, document, data=data, raw_text=raw_text, error=error)
        document.status = DocumentStatus.flagged.value if issues else DocumentStatus.extracted.value
        db.commit()

        self._check_conflicts(db, document)

    def _validate_field_formats(self, data: dict) -> list[dict]:
        """Does each value's apparent shape match what its field name
        implies? Catches a field whose value is self-evidently the wrong
        kind of thing for its key (e.g. an email address under a
        `*_telephone_number` key) — the signature of a source PDF whose
        AcroForm field names don't match their printed position (see
        `_FORM_FIELD_BOOLEAN_NOTE`). Unlike `_validate_doc_type`, this needs
        the actual values, not just field names.
        """
        if not data:
            return []
        client = get_llm_client()
        try:
            result = client.complete_json(
                system=_FIELD_VALUE_SANITY_SYSTEM,
                user=json.dumps(data),
            )
        except LLMError:
            # Fail open: an LLM hiccup on the validation step shouldn't sink
            # an otherwise-successful extraction.
            return []
        return [i for i in result.get("issues", []) if i.get("field") in data]

    def _format_issues(self, issues: list[dict]) -> str:
        parts = [f"{i.get('field', '?')}: {i.get('reason', '')}" for i in issues]
        return "Field value looks inconsistent with its name: " + "; ".join(parts)

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
            document.extraction.error = self._append_error(
                document.extraction.error,
                f"Possible identity conflict with {sibling.doc_type} document: {reason}",
            )
            sibling.status = DocumentStatus.flagged.value
            sibling.extraction.error = self._append_error(
                sibling.extraction.error,
                f"Possible identity conflict with {document.doc_type} document: {reason}",
            )
            db.commit()

    def _append_error(self, existing: str | None, new: str) -> str:
        """A document can be flagged for more than one reason (e.g. a field
        format issue found at extraction time, then an identity conflict
        found afterward) — append rather than overwrite so an earlier flag
        reason isn't silently lost."""
        return f"{existing}; {new}" if existing else new

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
        if document.doc_type == "passport":
            data = self._merge_mrz(data, raw_text)
        return data, raw_text

    # MRZ field -> canonical extraction-prompt key it should overwrite, and
    # the mrz_*_valid flag gating that overwrite (None if TD3 has no
    # per-field check digit for it — those are gated by the composite check
    # alone, i.e. by `extract_mrz_fields` having returned anything at all).
    _MRZ_TO_CANONICAL = {
        "mrz_surname": ("surname", None),
        "mrz_given_names": ("given_names", None),
        "mrz_passport_number": ("passport_number", "mrz_passport_number_valid"),
        "mrz_nationality": ("nationality", None),
        "mrz_date_of_birth": ("date_of_birth", "mrz_date_of_birth_valid"),
        "mrz_sex": ("sex", None),
        "mrz_date_of_expiry": ("date_of_expiry", "mrz_date_of_expiry_valid"),
    }

    def _merge_mrz(self, data: dict, raw_text: str) -> dict:
        """Passport-only: overlay checksum-validated MRZ fields onto `data`.

        MRZ is language-independent Latin/ASCII ground truth, so for the
        canonical fields it covers it's more trustworthy than the LLM's free
        text read of a non-English bio page. Runs *after* the LLM call and
        overwrites wholesale — MRZ values are deliberately never passed
        through the passport prompt's translation/transliteration
        instruction, since they're already Latin/ASCII by ICAO spec. Fails
        open: if no valid MRZ is found (composite check fails, or none
        present — most test PDFs, cropped/bad-quality images, etc.), `data`
        is returned unmodified.
        """
        mrz = extract_mrz_fields(raw_text)
        if not mrz:
            return data
        merged = {**data, **mrz}
        for mrz_key, (canonical_key, valid_flag_key) in self._MRZ_TO_CANONICAL.items():
            if mrz.get(mrz_key) is None:
                continue
            if valid_flag_key is not None and not mrz.get(valid_flag_key, False):
                continue
            merged[canonical_key] = mrz[mrz_key]
        return merged

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

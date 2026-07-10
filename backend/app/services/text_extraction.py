"""PDF text-layer extraction and rasterization, via pypdfium2.

Born-digital PDFs (G-28s filled in a PDF editor, etc.) carry their text as a
real text layer; reading it directly is fast and free. Scanned PDFs have no
text layer (or only a few stray characters), so callers fall back to
rasterizing pages to images and OCR-ing them (see `app.services.ocr`).
"""
from app.core.logging import get_logger

logger = get_logger(__name__)

# Below this many characters, treat the "text layer" as noise (e.g. a scanned
# PDF with a handful of embedded annotation glyphs) and fall back to OCR.
_MIN_TEXT_CHARS = 20


def pdf_text_layer(data: bytes) -> str:
    """Concatenate the embedded text layer across all pages of a PDF."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    try:
        pages_text = []
        for page in pdf:
            textpage = page.get_textpage()
            try:
                pages_text.append(textpage.get_text_bounded())
            finally:
                textpage.close()
            page.close()
        return "\n\n".join(pages_text)
    finally:
        pdf.close()


def has_text_layer(text: str) -> bool:
    return len(text.strip()) >= _MIN_TEXT_CHARS


def form_field_text(data: bytes) -> str:
    """AcroForm field values, as `field_name: value` lines.

    Fillable PDFs (e.g. USCIS forms completed in a PDF editor) store answers
    as interactive form-field widgets, not in the page content stream — so
    `pdf_text_layer` alone sees only the blank template's printed labels.
    Reading `/Annots` per page (rather than the `/AcroForm` field tree) is
    deliberate: some real-world PDFs have a malformed field tree that makes
    `PdfReader.get_fields()` miss most fields, while every filled widget is
    still reachable off its page's annotations.

    Checkbox/radio widgets (`/FT == "/Btn"`) always emit a `true`/`false`
    line — checked *and* unchecked — rather than being included only when
    checked. This gives the downstream LLM call a consistent signal to
    render these as JSON booleans (see `_FORM_FIELD_BOOLEAN_NOTE` in
    `extraction.py`), so stream 3's mapper can later tell "this is a
    checkbox" from the `data` dict's value type alone. `/AS` (the widget's
    own appearance state) is used rather than `/V`, since `/V` on a radio
    button's kid widget may be inherited from a shared parent field rather
    than reflecting that specific widget's state.
    """
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    lines = []
    for page in reader.pages:
        for annot in page.get("/Annots") or []:
            obj = annot.get_object()
            if obj.get("/Subtype") != "/Widget":
                continue
            name = obj.get("/T")
            if not name:
                continue
            if obj.get("/FT") == "/Btn":
                checked = obj.get("/AS", obj.get("/V")) not in (None, "/Off")
                lines.append(f"{name}: {'true' if checked else 'false'}")
                continue
            value = obj.get("/V")
            if not value:
                continue
            lines.append(f"{name}: {str(value).lstrip('/')}")
    return "\n".join(lines)


def rasterize_pdf(data: bytes, scale: float = 2.0) -> list[bytes]:
    """Render each page of a PDF to PNG bytes, for OCR input."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    try:
        images = []
        for page in pdf:
            bitmap = page.render(scale=scale)
            pil_image = bitmap.to_pil()
            import io

            buf = io.BytesIO()
            pil_image.save(buf, format="PNG")
            images.append(buf.getvalue())
            page.close()
        return images
    finally:
        pdf.close()

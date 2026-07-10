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

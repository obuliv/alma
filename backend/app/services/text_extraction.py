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


_MAX_PARENT_DEPTH = 8


def _resolve_field(obj):
    """Climb `/Parent` for the `/T` (name) and `/FT` (type) a widget doesn't
    carry itself.

    Radio-button groups are the standard case: one field object holds
    `/T`/`/FT`, and each option is a **kid** widget annotation with neither —
    both are inherited. Bounded depth guards against a cyclic/malformed
    chain in a real-world PDF.
    """
    name = None
    ft = None
    node = obj
    depth = 0
    while node is not None and depth < _MAX_PARENT_DEPTH and (name is None or ft is None):
        if name is None:
            name = node.get("/T")
        if ft is None:
            ft = node.get("/FT")
        parent = node.get("/Parent")
        node = parent.get_object() if parent is not None else None
        depth += 1
    return name, ft


def _btn_on_state(obj):
    """A Btn widget's own "checked" export value (e.g. "Married"), from its
    `/AP /N` appearance subdictionary keys (whichever isn't `/Off`) — not
    `/AS`, which is just the *current* state and would be `/Off` for every
    unselected option in a group."""
    ap = obj.get("/AP")
    normal = ap.get("/N") if ap else None
    if normal and hasattr(normal, "keys"):
        for key in normal.keys():
            if key != "/Off":
                return str(key).lstrip("/")
    as_state = obj.get("/AS")
    if as_state and as_state != "/Off":
        return str(as_state).lstrip("/")
    return None


def _choice_text(obj):
    """A `/Ch` field's selected display text via `/Opt` + `/I`, for
    list/combo boxes that carry a selected index but no `/V`."""
    opt, idx = obj.get("/Opt"), obj.get("/I")
    if not opt or not idx:
        return None
    selected = []
    for i in idx:
        try:
            entry = opt[int(i)]
        except (IndexError, TypeError, ValueError):
            continue
        selected.append(str(entry[1] if isinstance(entry, list) else entry))
    return ", ".join(selected) if selected else None


def form_field_text(data: bytes) -> str:
    """AcroForm field values, as `field_name: value` lines.

    Fillable PDFs (e.g. USCIS forms completed in a PDF editor) store answers
    as interactive form-field widgets, not in the page content stream — so
    `pdf_text_layer` alone sees only the blank template's printed labels.
    Reading `/Annots` per page (rather than the `/AcroForm` field tree) is
    deliberate: some real-world PDFs have a malformed field tree that makes
    `PdfReader.get_fields()` miss most fields, while every filled widget is
    still reachable off its page's annotations. Widgets are resolved to
    their field name/type via `_resolve_field` (see there for why) and
    grouped by name before any line is emitted.

    Checkbox/radio widgets (`/FT == "/Btn"`) always emit a `true`/`false`
    line — checked *and* unchecked — rather than being included only when
    checked. This gives the downstream LLM call a consistent signal to
    render these as JSON booleans (see `_FORM_FIELD_BOOLEAN_NOTE` in
    `extraction.py`), so stream 3's mapper can later tell "this is a
    checkbox" from the `data` dict's value type alone. A lone checkbox
    emits one `name: true/false` line off its own `/AS`. A **group** of Btn
    kids (radio buttons) instead emits one `name.option: true/false` line
    per option (see `_btn_on_state`) — collapsing a multi-option group into
    a single `name: true/false` line would report that something was
    checked without saying which option.

    Text (`/Tx`) and choice (`/Ch`) fields take the first non-empty `/V`
    among their widgets — covers both the ordinary case and a field
    duplicated as a kid across pages. A `/Ch` field with no `/V` falls back
    to `_choice_text` (`/Opt` + `/I`).
    """
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))

    groups: dict[str, list] = {}
    order: list[str] = []
    for page in reader.pages:
        for annot in page.get("/Annots") or []:
            obj = annot.get_object()
            if obj.get("/Subtype") != "/Widget":
                continue
            name, ft = _resolve_field(obj)
            if not name:
                continue
            name = str(name)
            if name not in groups:
                groups[name] = []
                order.append(name)
            groups[name].append((obj, ft))

    lines = []
    for name in order:
        widgets = groups[name]
        ft = next((f for _, f in widgets if f), None)

        if ft == "/Btn":
            if len(widgets) == 1:
                obj, _ = widgets[0]
                checked = obj.get("/AS", obj.get("/V")) not in (None, "/Off")
                lines.append(f"{name}: {'true' if checked else 'false'}")
            else:
                for obj, _ in widgets:
                    on_state = _btn_on_state(obj)
                    if not on_state:
                        continue
                    as_state = obj.get("/AS")
                    checked = as_state is not None and str(as_state).lstrip("/") == on_state
                    lines.append(f"{name}.{on_state}: {'true' if checked else 'false'}")
            continue

        value = next((obj.get("/V") for obj, _ in widgets if obj.get("/V")), None)
        if not value and ft == "/Ch":
            value = next((t for obj, _ in widgets if (t := _choice_text(obj))), None)
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

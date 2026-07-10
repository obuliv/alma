"""OCR engine abstraction — turns page images into text.

Selected via `settings.ocr_mode`:
- "rapidocr": local PP-OCR models via onnxruntime; no external API call.
- "llm": Claude vision transcribes the page (one extra LLM call, only for
  documents/pages that need it).

Called by `ExtractionService._extract` only when a PDF has no usable text
layer (see `app.services.text_extraction.has_text_layer`), or for image
uploads, which have no text layer to check.
"""
from abc import ABC, abstractmethod

from app.config import settings
from app.core.errors import ExtractionError
from app.core.logging import get_logger
from app.services.llm import Attachment, get_llm_client

logger = get_logger(__name__)


class OCREngine(ABC):
    @abstractmethod
    def image_to_text(self, images: list[bytes]) -> str:
        """Return transcribed text for a document's page images, in order."""


class RapidOCREngine(OCREngine):
    """Local OCR via PP-OCR models (RapidOCR's onnxruntime port of PaddleOCR)."""

    # Model loading is expensive; share one engine instance across documents.
    _engine = None

    def _get_engine(self):
        if RapidOCREngine._engine is None:
            from rapidocr_onnxruntime import RapidOCR

            RapidOCREngine._engine = RapidOCR()
        return RapidOCREngine._engine

    def image_to_text(self, images: list[bytes]) -> str:
        engine = self._get_engine()
        pages = []
        for image_bytes in images:
            result, _ = engine(image_bytes)
            if result:
                pages.append("\n".join(line[1] for line in result))
        return "\n\n".join(pages)


class LLMVisionEngine(OCREngine):
    """Transcribes page images to text via the configured LLM's vision input."""

    _SYSTEM = (
        "Transcribe every piece of text visible in the attached document "
        "image(s) verbatim, in reading order. Output plain text only — no "
        "commentary, no markdown, no summarization."
    )

    def image_to_text(self, images: list[bytes]) -> str:
        client = get_llm_client()
        attachments: list[Attachment] = [(img, "image/png") for img in images]
        return client.complete_vision(
            system=self._SYSTEM,
            user="Transcribe this document.",
            attachments=attachments,
        )


def get_ocr_engine() -> OCREngine:
    """Factory — selects the implementation from `settings.ocr_mode`."""
    mode = settings.ocr_mode.lower()
    if mode == "rapidocr":
        return RapidOCREngine()
    if mode == "llm":
        return LLMVisionEngine()
    raise ExtractionError(f"Unsupported OCR mode: {settings.ocr_mode!r}")

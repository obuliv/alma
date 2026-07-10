"""Provider-agnostic LLM client shared by both workstreams.

- Stream 2 (extraction): `complete_json(system, user, attachments=<doc files>)`
  where attachments are the passport/G-28 images or PDFs.
- Stream 3 (form-fill mapping): `complete_json(system, user)` with the form's
  fields + the merged application data, returning `{form_field: value}`.

The client stays generic; prompts live in the calling services. Swap providers
via `settings.llm_provider` — implementations only need to satisfy `LLMClient`.
"""
import json
from abc import ABC, abstractmethod

from app.config import settings
from app.core.errors import LLMError
from app.core.logging import get_logger

logger = get_logger(__name__)

# (bytes, media_type) — e.g. (b"...", "image/png") or (b"...", "application/pdf")
Attachment = tuple[bytes, str]

_MAX_ATTEMPTS = 2


class LLMClient(ABC):
    @abstractmethod
    def complete(self, system: str, user: str) -> str:
        """Return the model's text response."""

    @abstractmethod
    def complete_json(
        self, system: str, user: str, attachments: list[Attachment] | None = None
    ) -> dict:
        """Return the model's response parsed as a JSON object."""


def _strip_json_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        # remove leading ```json / ``` and trailing ```
        t = t.split("\n", 1)[1] if "\n" in t else t
        if t.endswith("```"):
            t = t[: -3]
    return t.strip()


class AnthropicLLMClient(LLMClient):
    def __init__(self) -> None:
        if not settings.anthropic_api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set.")
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise LLMError("anthropic SDK is not installed.") from exc
        self._client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key,
            timeout=settings.llm_timeout_s,
        )

    def _build_content(self, user: str, attachments: list[Attachment] | None) -> list[dict]:
        import base64

        blocks: list[dict] = []
        for data, media_type in attachments or []:
            b64 = base64.standard_b64encode(data).decode()
            source = {"type": "base64", "media_type": media_type, "data": b64}
            block_type = "document" if media_type == "application/pdf" else "image"
            blocks.append({"type": block_type, "source": source})
        blocks.append({"type": "text", "text": user})
        return blocks

    def _call(self, system: str, content: list[dict]) -> str:
        last_exc: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                msg = self._client.messages.create(
                    model=settings.llm_model,
                    max_tokens=settings.llm_max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": content}],
                )
                return "".join(
                    block.text for block in msg.content if block.type == "text"
                )
            except Exception as exc:  # noqa: BLE001 - normalize to LLMError
                last_exc = exc
                logger.warning("LLM call failed (attempt %d/%d): %s", attempt, _MAX_ATTEMPTS, exc)
        raise LLMError(f"LLM call failed: {last_exc}")

    def complete(self, system: str, user: str) -> str:
        return self._call(system, [{"type": "text", "text": user}])

    def complete_json(
        self, system: str, user: str, attachments: list[Attachment] | None = None
    ) -> dict:
        json_system = f"{system}\n\nRespond with a single valid JSON object and nothing else."
        content = self._build_content(user, attachments)
        raw = self._call(json_system, content)
        try:
            parsed = json.loads(_strip_json_fences(raw))
        except json.JSONDecodeError as exc:
            raise LLMError(f"LLM did not return valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise LLMError("LLM JSON response was not an object.")
        return parsed


def get_llm_client() -> LLMClient:
    """Factory — selects the implementation from `settings.llm_provider`."""
    provider = settings.llm_provider.lower()
    if provider == "anthropic":
        return AnthropicLLMClient()
    raise LLMError(f"Unsupported LLM provider: {settings.llm_provider!r}")

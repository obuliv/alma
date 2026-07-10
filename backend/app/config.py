from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://alma:alma@db:5432/alma"

    # Where uploaded files are written on the mounted volume.
    upload_dir: str = "/data/uploads"

    max_upload_mb: int = 10

    # Content types accepted for uploads (validated by magic bytes, not client header).
    allowed_content_types: tuple[str, ...] = (
        "application/pdf",
        "image/jpeg",
        "image/png",
    )

    # Comma-separated origins for CORS. Same-origin (nginx proxy) needs none;
    # this is a convenience for running the frontend dev server separately.
    cors_origins: str = ""

    # --- LLM (shared by extraction + form-fill mapping) ---
    # Values/secrets come from .env; only defaults live here.
    llm_provider: str = "anthropic"
    anthropic_api_key: str = ""
    llm_model: str = "claude-opus-4-8"
    llm_max_tokens: int = 4096
    llm_timeout_s: int = 60

    # Text-extraction engine used when a PDF has no embedded text layer, or for
    # image uploads: "llm" (Claude vision transcribes the page) or "rapidocr"
    # (local PP-OCR models via onnxruntime, no external API call).
    ocr_mode: str = "llm"

    # --- Browser automation (stream 3) ---
    form_url: str = ""
    browser_headless: bool = True
    browser_timeout_ms: int = 30000

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

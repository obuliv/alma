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

"""Form-fill service — STUB (stream 3 lands browser automation here).

Entry point for populating the target form with an application's merged
extraction data via browser automation (Playwright).

Import-safe by design: Playwright is imported lazily inside `fill`, so this
module imports cleanly in the `api` image (which has no browser deps). The real
worker runs in the `automation` container (see automation/Dockerfile).

Form-agnostic: nothing here assumes a specific form or a fixed set of extracted
fields. The mapping is generated from **two sets of dict keys** — the extracted
data's keys and the form's field keys — so it adapts to whatever each side has.

Intended flow (stream 3):
  1. `data = build_application_data(application)`  # merged {passport, g28}, arbitrary keys
  2. open `form_url`, scrape the form's field keys (name/label/selector)
  3. `mapping = get_llm_client().complete_json(...)` given the two key-sets
     (extracted-data keys + form-field keys) -> {form_field: extracted_value}
  4. fill each mapped field via Playwright
"""
import uuid

from sqlalchemy.orm import Session

from app.config import settings
from app.core.errors import FormFillError
from app.core.logging import get_logger
from app.models import Application
from app.services.application_service import build_application_data

logger = get_logger(__name__)


class FormFillService:
    def fill(
        self, db: Session, application_id: uuid.UUID, form_url: str | None = None
    ) -> None:
        """STUB: drive a browser to fill the form from the application's merged
        data. Implemented in stream 3."""
        application = db.get(Application, application_id)
        if application is None:
            raise FormFillError(f"Application {application_id} not found")

        target_url = form_url or settings.form_url
        if not target_url:
            raise FormFillError("No form_url provided (set FORM_URL or pass one).")

        data = build_application_data(application)
        logger.info(
            "form-fill stub for application %s (case %s) -> %s; merged keys: %s",
            application.id,
            application.case_id,
            target_url,
            list(data.keys()),
        )

        # Lazy import keeps this module usable in the api image (no Playwright there).
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except ImportError as exc:
            raise FormFillError(
                "Playwright is not installed here. Run form-fill in the "
                "'automation' container (docker compose --profile worker)."
            ) from exc

        raise NotImplementedError("Form fill (stream 3) is not implemented yet.")


form_fill_service = FormFillService()

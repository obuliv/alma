"""Form-fill service (stream 3) — browser automation.

Scrapes the target form's fields, asks the LLM to map the application's merged
extraction data onto those fields, fills them in a **headed** browser, and
leaves the window open for the user to review/correct/submit.

Import-safe by design: Playwright is imported lazily inside `fill`, so this
module imports cleanly even where Playwright isn't installed. A visible
browser window requires a display, so `fill` is meant to run from a process
with one (e.g. `uvicorn` on your machine), not a headless server/CI box.

Form-agnostic: nothing here assumes a specific form or a fixed set of
extracted fields. The mapping is generated from **two sets of dict keys** —
the extracted data's keys and the scraped form's field keys — so it adapts to
whatever each side has.
"""
import json
import time
import uuid

from sqlalchemy.orm import Session

from app.config import settings
from app.core.errors import FormFillError
from app.core.logging import get_logger
from app.models import Application, FormFillRun, FormFillRunStatus
from app.services.application_service import build_application_data
from app.services.llm import get_llm_client

logger = get_logger(__name__)

_POLL_S = 1.0

_MAP_SYSTEM_PROMPT = (
    "You map extracted applicant data onto a target web form's fields. Given "
    "the applicant's data (grouped by document type) and the form's fields "
    "(selector, label, input_type, options), return a single JSON object "
    "mapping each field's selector to the value that should be typed/selected "
    "into it. Only include selectors you are confident about; omit fields you "
    "cannot map. For 'select' fields, the value must be one of the given "
    "options. For checkboxes/radios, use \"true\" or \"false\"."
)


class FormFillService:
    def fill(self, db: Session, run_id: uuid.UUID) -> None:
        """Detect fields, map data onto them, fill the form, and hold the
        browser open. Marks the run `filled` or `failed`."""
        run = db.get(FormFillRun, run_id)
        if run is None:
            return

        application = db.get(Application, run.application_id)
        data = build_application_data(application)

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            self._fail(
                db,
                run,
                "Playwright is not installed here. Run the API on a host with "
                "`pip install playwright==1.49.0 && playwright install chromium`.",
            )
            logger.error("form-fill %s: %s", run.id, exc)
            return

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=False)
                page = browser.new_page()
                page.goto(run.form_url, timeout=settings.browser_timeout_ms)

                fields = self._scrape_fields(page)
                mapping = self._map_fields(data, fields)
                self._apply(page, fields, mapping)

                run.fields = fields
                run.mapping = mapping
                run.status = FormFillRunStatus.filled.value
                db.commit()
                logger.info(
                    "form-fill %s: filled %d field(s), leaving browser open",
                    run.id,
                    len(mapping),
                )

                self._wait_until_closed(page)
                browser.close()
        except Exception as exc:  # noqa: BLE001 - record any failure on the run
            self._fail(db, run, str(exc))
            logger.exception("form-fill %s failed", run.id)

    def _fail(self, db: Session, run: FormFillRun, error: str) -> None:
        run.status = FormFillRunStatus.failed.value
        run.error = error
        db.commit()

    def _wait_until_closed(self, page) -> None:
        while True:
            try:
                if page.is_closed():
                    return
            except Exception:
                return
            time.sleep(_POLL_S)

    def _scrape_fields(self, page) -> list[dict]:
        """Enumerate fillable controls: selector, label, input type, options."""
        return page.evaluate(
            """
            () => {
              const controls = Array.from(
                document.querySelectorAll('input, select, textarea')
              );
              return controls
                .filter(el => !['hidden', 'submit', 'button', 'reset']
                  .includes((el.type || '').toLowerCase()))
                .map(el => {
                  let selector;
                  if (el.id) selector = '#' + CSS.escape(el.id);
                  else if (el.name) selector = `[name="${el.name}"]`;
                  else return null;

                  let label = '';
                  if (el.id) {
                    const lbl = document.querySelector(`label[for="${el.id}"]`);
                    if (lbl) label = lbl.textContent.trim();
                  }
                  if (!label) label = el.getAttribute('aria-label') || '';
                  if (!label) label = el.getAttribute('placeholder') || '';
                  if (!label) label = el.name || el.id || '';

                  const tag = el.tagName.toLowerCase();
                  return {
                    selector,
                    label,
                    input_type: tag === 'select' ? 'select'
                      : tag === 'textarea' ? 'textarea'
                      : (el.type || 'text').toLowerCase(),
                    options: tag === 'select'
                      ? Array.from(el.options).map(o => o.value)
                      : null,
                  };
                })
                .filter(f => f !== null);
            }
            """
        )

    def _map_fields(self, data: dict, fields: list[dict]) -> dict:
        if not fields:
            return {}
        user = (
            f"Applicant data:\n{json.dumps(data)}\n\n"
            f"Form fields:\n{json.dumps(fields)}\n\n"
            "Respond with {selector: value}."
        )
        try:
            return get_llm_client().complete_json(_MAP_SYSTEM_PROMPT, user)
        except Exception as exc:
            raise FormFillError(f"Field-mapping LLM call failed: {exc}") from exc

    def _apply(self, page, fields: list[dict], mapping: dict) -> None:
        by_selector = {f["selector"]: f for f in fields}
        timeout = settings.browser_timeout_ms
        for selector, value in mapping.items():
            field = by_selector.get(selector)
            if field is None or value is None:
                continue
            try:
                if field["input_type"] == "select":
                    page.select_option(selector, str(value), timeout=timeout)
                elif field["input_type"] in ("checkbox", "radio"):
                    truthy = str(value).strip().lower() in ("true", "1", "yes", "on")
                    (page.check if truthy else page.uncheck)(selector, timeout=timeout)
                else:
                    page.fill(selector, str(value), timeout=timeout)
            except Exception as exc:  # noqa: BLE001 - skip fields that fail to fill
                logger.warning("form-fill: could not apply %s -> %r: %s", selector, value, exc)


form_fill_service = FormFillService()

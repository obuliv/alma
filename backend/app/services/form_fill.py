"""Form-fill service — STUB (step 3 lands browser automation here).

This is the entry point for populating the target form URL with a document's
(or application's) extracted data via browser automation (e.g. Playwright).
It is intentionally not wired to an endpoint yet.
"""
import uuid

from sqlalchemy.orm import Session

from app.models import Application


class FormFillService:
    def fill(self, db: Session, application_id: uuid.UUID, form_url: str) -> None:
        """STUB: drive a browser to fill `form_url` from the application's
        merged extraction data. Implemented in step 3."""
        application = db.get(Application, application_id)
        if application is None:
            raise ValueError(f"Application {application_id} not found")
        raise NotImplementedError("Form fill (step 3) is not implemented yet.")


form_fill_service = FormFillService()

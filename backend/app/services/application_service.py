"""Application (case) grouping + merged-data view.

A `case_id` entered at upload groups a passport + G-28 under one `Application`.
`build_application_data` produces the merged view the fill-time LLM mapper
(stream 3) consumes to populate the target form.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Application, Document, FormFillRun


def get_or_create_by_case_id(db: Session, case_id: str) -> Application:
    """Return the application for `case_id`, creating it if absent.

    Caller is responsible for committing.
    """
    application = db.execute(
        select(Application).where(Application.case_id == case_id)
    ).scalar_one_or_none()
    if application is None:
        application = Application(case_id=case_id)
        db.add(application)
        db.flush()  # assign id so callers can associate documents
    return application


def build_application_data(application: Application) -> dict:
    """Merge each document's extraction data, keyed by doc_type.

    e.g. {"passport": {...}, "g28": {...}}. Documents without an extraction
    result yet contribute an empty dict.
    """
    merged: dict[str, dict] = {}
    for document in application.documents:
        merged[document.doc_type] = (
            document.extraction.data if document.extraction else {}
        )
    return merged


def get_application_documents(application: Application) -> list[Document]:
    return list(application.documents)


def create_run(db: Session, case_id: str, form_url: str) -> FormFillRun:
    """Create a form-fill run for `case_id`'s application against `form_url`.

    Caller is responsible for committing.
    """
    application = get_or_create_by_case_id(db, case_id)
    application.form_url = form_url
    run = FormFillRun(application_id=application.id, form_url=form_url)
    db.add(run)
    db.flush()  # assign run.id
    return run

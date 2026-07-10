import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.database import session_scope
from app.models import Application, FormFillRun
from app.schemas.form_fill import FormFillRunCreate, FormFillRunOut, FormFillRunSummary
from app.services.application_service import create_run
from app.services.form_fill import form_fill_service

router = APIRouter(prefix="/form-fill-runs", tags=["form-fill"])


def _run_form_fill(run_id: uuid.UUID) -> None:
    """Background entry point — uses its own transactional session."""
    with session_scope() as db:
        form_fill_service.fill(db, run_id)


def _to_summary(run: FormFillRun, case_id: str | None) -> FormFillRunSummary:
    return FormFillRunSummary(
        id=run.id,
        case_id=case_id,
        form_url=run.form_url,
        status=run.status,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _to_out(run: FormFillRun, case_id: str | None) -> FormFillRunOut:
    return FormFillRunOut(
        id=run.id,
        case_id=case_id,
        form_url=run.form_url,
        status=run.status,
        fields=run.fields,
        mapping=run.mapping,
        error=run.error,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


@router.post("", response_model=FormFillRunOut, status_code=status.HTTP_201_CREATED)
def create_form_fill_run(
    payload: FormFillRunCreate,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> FormFillRunOut:
    """Kick off a form-fill run: detect fields, map data, and open a headed
    browser to fill them. Runs in the background; poll GET to watch status."""
    run = create_run(db, payload.case_id, payload.form_url)
    db.commit()
    db.refresh(run)

    background.add_task(_run_form_fill, run.id)
    return _to_out(run, payload.case_id)


@router.get("", response_model=list[FormFillRunSummary])
def list_form_fill_runs(db: Session = Depends(get_db)) -> list[FormFillRunSummary]:
    rows = db.execute(
        select(FormFillRun, Application.case_id)
        .join(Application, Application.id == FormFillRun.application_id)
        .order_by(FormFillRun.created_at.desc())
    ).all()
    return [_to_summary(run, case_id) for run, case_id in rows]


@router.get("/{run_id}", response_model=FormFillRunOut)
def get_form_fill_run(run_id: uuid.UUID, db: Session = Depends(get_db)) -> FormFillRunOut:
    run = db.get(FormFillRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    application = db.get(Application, run.application_id)
    return _to_out(run, application.case_id if application else None)

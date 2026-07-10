from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models import Application
from app.schemas.application import ApplicationDetail, ApplicationSummary
from app.services.application_service import build_application_data

router = APIRouter(prefix="/applications", tags=["applications"])


@router.get("", response_model=list[ApplicationSummary])
def list_applications(db: Session = Depends(get_db)) -> list[Application]:
    return list(
        db.execute(select(Application).order_by(Application.created_at.desc()))
        .scalars()
        .all()
    )


@router.get("/{case_id}", response_model=ApplicationDetail)
def get_application(case_id: str, db: Session = Depends(get_db)) -> ApplicationDetail:
    application = db.execute(
        select(Application).where(Application.case_id == case_id)
    ).scalar_one_or_none()
    if application is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Application not found"
        )
    return ApplicationDetail(
        id=application.id,
        case_id=application.case_id,
        status=application.status,
        documents=application.documents,
        data=build_application_data(application),
    )

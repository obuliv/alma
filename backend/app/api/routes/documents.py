import uuid

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.validation import validate_and_sniff
from app.database import session_scope
from app.models import Document, DocumentFile, DocType, DocumentStatus
from app.schemas.document import DocumentOut, DocumentSummary
from app.services import storage
from app.services.application_service import get_or_create_by_case_id
from app.services.extraction import extraction_service

router = APIRouter(prefix="/documents", tags=["documents"])


def _run_extraction(document_id: uuid.UUID) -> None:
    """Background entry point — uses its own transactional session."""
    with session_scope() as db:
        extraction_service.run(db, document_id)


def _parse_doc_type(doc_type: str) -> str:
    try:
        return DocType(doc_type).value
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"doc_type must be one of: {[t.value for t in DocType]}",
        )


async def _persist_files(
    db: Session, document: Document, files: list[UploadFile], start_order: int
) -> None:
    """Validate, store, and record each uploaded file for a document."""
    order = start_order
    for file in files:
        data = await file.read()
        content_type = validate_and_sniff(file, data)
        path = storage.save_file(document.id, data, content_type)
        db.add(
            DocumentFile(
                document_id=document.id,
                original_filename=file.filename or "upload",
                content_type=content_type,
                file_path=path,
                file_size=len(data),
                page_order=order,
            )
        )
        order += 1


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def create_document(
    background: BackgroundTasks,
    doc_type: str = Form(...),
    files: list[UploadFile] = File(...),
    case_id: str = Form(...),
    db: Session = Depends(get_db),
) -> Document:
    """Upload one or many files as a single logical document.

    `case_id` groups the document with others under one application
    (get-or-create), so a passport + G-28 share the same case.
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="At least one file is required."
        )
    if not case_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="case_id is required."
        )
    doc_type_value = _parse_doc_type(doc_type)

    document = Document(doc_type=doc_type_value, status=DocumentStatus.uploaded.value)
    application = get_or_create_by_case_id(db, case_id.strip())
    document.application_id = application.id
    db.add(document)
    db.flush()  # assign document.id before saving files

    await _persist_files(db, document, files, start_order=0)
    db.commit()
    db.refresh(document)

    background.add_task(_run_extraction, document.id)
    return document


@router.post("/{document_id}/files", response_model=DocumentOut)
async def append_files(
    document_id: uuid.UUID,
    background: BackgroundTasks,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
) -> Document:
    """Append more files/pages to an existing document and re-run extraction."""
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="At least one file is required."
        )

    next_order = (max((f.page_order for f in document.files), default=-1)) + 1
    await _persist_files(db, document, files, start_order=next_order)
    document.status = DocumentStatus.uploaded.value
    db.commit()
    db.refresh(document)

    background.add_task(_run_extraction, document.id)
    return document


@router.get("", response_model=list[DocumentSummary])
def list_documents(db: Session = Depends(get_db)) -> list[DocumentSummary]:
    rows = db.execute(
        select(
            Document,
            func.count(DocumentFile.id).label("file_count"),
        )
        .outerjoin(DocumentFile, DocumentFile.document_id == Document.id)
        .group_by(Document.id)
        .order_by(Document.created_at.desc())
    ).all()
    return [
        DocumentSummary(
            id=doc.id,
            doc_type=doc.doc_type,
            status=doc.status,
            file_count=count,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
        )
        for doc, count in rows
    ]


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: uuid.UUID, db: Session = Depends(get_db)) -> Document:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document


@router.get("/{document_id}/files/{file_id}")
def download_file(
    document_id: uuid.UUID, file_id: uuid.UUID, db: Session = Depends(get_db)
) -> Response:
    file = db.get(DocumentFile, file_id)
    if file is None or file.document_id != document_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return Response(
        content=storage.read_file(file.file_path),
        media_type=file.content_type,
        headers={
            "Content-Disposition": f'inline; filename="{file.original_filename}"'
        },
    )


@router.delete("/{document_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(
    document_id: uuid.UUID, file_id: uuid.UUID, db: Session = Depends(get_db)
) -> Response:
    file = db.get(DocumentFile, file_id)
    if file is None or file.document_id != document_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    storage.delete_file(file.file_path)
    db.delete(file)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

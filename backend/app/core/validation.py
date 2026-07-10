import filetype
from fastapi import HTTPException, UploadFile, status

from app.config import settings

# Map sniffed magic-byte type -> canonical content type we store.
_ALLOWED_EXTENSIONS = {"pdf", "jpg", "png"}
_EXT_TO_CONTENT_TYPE = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg",
    "png": "image/png",
}


def validate_and_sniff(file: UploadFile, data: bytes) -> str:
    """Validate an uploaded file's size and true type.

    Returns the canonical content type derived from magic bytes (not the
    client-supplied header). Raises HTTPException on any violation.
    """
    if len(data) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File '{file.filename}' is empty.",
        )

    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"File '{file.filename}' exceeds the "
                f"{settings.max_upload_mb} MB limit."
            ),
        )

    kind = filetype.guess(data)
    if kind is None or kind.extension not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"File '{file.filename}' is not a supported type. "
                "Only PDF, JPEG, and PNG are allowed."
            ),
        )

    return _EXT_TO_CONTENT_TYPE[kind.extension]

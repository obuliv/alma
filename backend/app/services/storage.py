import uuid
from pathlib import Path

from app.config import settings

_CONTENT_TYPE_EXT = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
}


def _root() -> Path:
    root = Path(settings.upload_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def save_file(document_id: uuid.UUID, data: bytes, content_type: str) -> str:
    """Persist bytes under the document's directory. Returns the stored path."""
    doc_dir = _root() / str(document_id)
    doc_dir.mkdir(parents=True, exist_ok=True)
    ext = _CONTENT_TYPE_EXT.get(content_type, "")
    path = doc_dir / f"{uuid.uuid4()}{ext}"
    path.write_bytes(data)
    return str(path)


def read_file(file_path: str) -> bytes:
    return Path(file_path).read_bytes()


def delete_file(file_path: str) -> None:
    Path(file_path).unlink(missing_ok=True)

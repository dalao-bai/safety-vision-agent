from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import get_settings, resolve_project_path
from app.db.models import UploadedFile


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def ensure_runtime_dirs() -> None:
    settings = get_settings()
    db_path = settings.database_file_path
    if db_path:
        ensure_parent_dir(db_path)
    settings.upload_path.mkdir(parents=True, exist_ok=True)
    settings.output_path.mkdir(parents=True, exist_ok=True)
    settings.report_path.mkdir(parents=True, exist_ok=True)


def resolve_upload_target(filename: str) -> Path:
    settings = get_settings()
    upload_dir = settings.upload_path
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = (upload_dir / filename).resolve()
    if not is_within_directory(target, upload_dir):
        raise HTTPException(status_code=400, detail="invalid upload target")
    return target


def get_uploaded_image_path(db: Session, file_id: str | None, image_path: str | None) -> str:
    if file_id:
        record = db.get(UploadedFile, file_id)
        if not record:
            raise HTTPException(status_code=404, detail="uploaded file not found")
        return validate_uploaded_path(record.stored_path)

    if image_path:
        return validate_uploaded_path(image_path)

    raise HTTPException(status_code=400, detail="file_id or image_path is required")


def validate_uploaded_path(image_path: str) -> str:
    settings = get_settings()
    upload_dir = settings.upload_path
    path = Path(image_path)
    if not path.is_absolute():
        path = resolve_project_path(image_path)
    else:
        path = path.resolve()

    if not is_within_directory(path, upload_dir):
        raise HTTPException(status_code=400, detail="image_path must reference an uploaded file")
    if not path.exists():
        raise HTTPException(status_code=404, detail="uploaded image not found")
    return path.as_posix()


def is_within_directory(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory.resolve())
        return True
    except ValueError:
        return False

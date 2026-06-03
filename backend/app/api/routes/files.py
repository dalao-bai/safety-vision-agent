from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.repositories import add_uploaded_file
from app.db.session import get_db
from app.models.schemas import UploadedImageResponse


router = APIRouter()

ALLOWED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
ALLOWED_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp", "image/bmp"}


@router.post("/images", response_model=UploadedImageResponse)
async def upload_image(file: UploadFile = File(...), db: Session = Depends(get_db)) -> UploadedImageResponse:
    settings = get_settings()
    suffix = Path(file.filename or "image").suffix.lower() or ".jpg"
    if suffix not in ALLOWED_IMAGE_SUFFIXES:
        raise HTTPException(status_code=400, detail="unsupported image file extension")
    if file.content_type and file.content_type not in ALLOWED_IMAGE_MIME_TYPES:
        raise HTTPException(status_code=400, detail="unsupported image content type")

    data = await file.read()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=f"image exceeds {settings.max_upload_size_mb} MB limit")

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    file_id = f"img_{uuid4().hex}"
    target = upload_dir / f"{file_id}{suffix}"
    target.write_bytes(data)

    record = add_uploaded_file(
        db=db,
        original_name=file.filename or target.name,
        stored_path=target.as_posix(),
        mime_type=file.content_type,
    )

    return UploadedImageResponse(
        file_id=record.id,
        filename=record.original_name,
        path=record.stored_path,
    )

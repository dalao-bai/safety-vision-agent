from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.core.config import get_settings
from app.db.repositories import add_uploaded_file
from app.models.schemas import UploadedImageResponse
from app.services.file_storage import resolve_upload_target


router = APIRouter()

ALLOWED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
ALLOWED_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp", "image/bmp"}


@router.post("/images", response_model=UploadedImageResponse)
async def upload_image(file: UploadFile = File(...)) -> UploadedImageResponse:
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

    file_id = f"img_{uuid4().hex}"
    target = resolve_upload_target(f"{file_id}{suffix}")
    target.write_bytes(data)

    record = add_uploaded_file(
        original_name=file.filename or target.name,
        stored_path=target.as_posix(),
        mime_type=file.content_type,
    )

    return UploadedImageResponse(
        file_id=record.id,
        filename=record.original_name,
        path=record.stored_path,
    )

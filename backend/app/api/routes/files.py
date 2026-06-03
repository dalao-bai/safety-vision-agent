from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.repositories import add_uploaded_file
from app.db.session import get_db
from app.models.schemas import UploadedImageResponse


router = APIRouter()


@router.post("/images", response_model=UploadedImageResponse)
async def upload_image(file: UploadFile = File(...), db: Session = Depends(get_db)) -> UploadedImageResponse:
    settings = get_settings()
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename or "image").suffix or ".jpg"
    file_id = f"img_{uuid4().hex}"
    target = upload_dir / f"{file_id}{suffix}"
    target.write_bytes(await file.read())

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

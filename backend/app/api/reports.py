from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

import app.api.deps as deps
from app.config import get_settings

router = APIRouter()


@router.get("/sessions/{sid}/report/download")
def download_report(sid: str, db=Depends(deps.get_db)):
    if not db.session_exists(sid):
        raise HTTPException(404, "session not found")
    path = Path(get_settings().report_dir) / f"session_{sid}_report.docx"
    if not path.exists():
        raise HTTPException(404, "report not generated")
    return FileResponse(str(path),
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        filename=path.name)

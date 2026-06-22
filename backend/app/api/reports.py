from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

import app.api.deps as deps
from app.config import get_settings
from app.reports.builder import build_markdown_report

router = APIRouter()


@router.post("/sessions/{sid}/report")
def make_report(sid: int, db=Depends(deps.get_db), kg=Depends(deps.get_kg)):
    if not db.session_exists(sid):
        raise HTTPException(404, "session not found")
    settings = get_settings()
    hazards = db.get_confirmed_hazards(sid)
    path = build_markdown_report(
        session_id=sid, hazards=hazards, report_dir=settings.report_dir,
        object_name_for=lambda oid: (kg.get_object(oid) or {}).get("name", oid),
        hazard_name_for=lambda hid: (kg.get_hazard_type(hid) or {}).get("name", hid or ""),
        remediation_for=kg.remediation_for)
    return {"report_path": path}


@router.get("/sessions/{sid}/report/download")
def download_report(sid: int, db=Depends(deps.get_db)):
    if not db.session_exists(sid):
        raise HTTPException(404, "session not found")
    path = Path(get_settings().report_dir) / f"session_{sid}_report.md"
    if not path.exists():
        raise HTTPException(404, "report not generated")
    return FileResponse(str(path), media_type="text/markdown", filename=path.name)

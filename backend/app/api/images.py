from __future__ import annotations

import hashlib
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

import app.api.deps as deps
from app.agent.orchestrator import Orchestrator
from app.agent.tools import ToolContext
from app.config import get_settings
from app.vlm.detector import DetectionError

router = APIRouter()

_ALLOWED = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def _save_upload(data: bytes, sid: int, suffix: str, upload_dir: Path) -> str:
    upload_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(data).hexdigest()[:16]
    dest = (upload_dir / f"{sid}_{digest}{suffix}").resolve()
    if not dest.is_relative_to(upload_dir.resolve()):
        raise ValueError("invalid path")
    dest.write_bytes(data)
    return str(dest)


def _make_orch(db, agent_client, kg, standards, intake, settings):
    ctx_factory = lambda session_id: ToolContext(
        db=db, kg=kg, standards=standards, intake=intake,
        report_dir=settings.report_dir, session_id=session_id)
    return Orchestrator(db=db, agent_client=agent_client, agent_model=settings.agent_model,
                        ctx_factory=ctx_factory, max_iterations=settings.max_tool_iterations)


@router.post("/sessions/{sid}/images")
def upload_image(sid: int, file: UploadFile = File(...),
                 db=Depends(deps.get_db), kg=Depends(deps.get_kg),
                 detector=Depends(deps.get_detector),
                 agent_client=Depends(deps.get_agent_client),
                 intake=Depends(deps.get_intake),
                 standards=Depends(deps.get_standards)):
    if not db.session_exists(sid):
        raise HTTPException(404, "session not found")
    settings = get_settings()
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED:
        raise HTTPException(400, f"unsupported image type: {suffix}")
    data = file.file.read(settings.max_image_bytes + 1)
    if len(data) > settings.max_image_bytes:
        raise HTTPException(413, "image too large")

    path = _save_upload(data, sid, suffix, Path(settings.upload_dir))
    try:
        result = detector.detect(path)
    except DetectionError as exc:
        raise HTTPException(422, f"识别失败: {exc}")

    orch = _make_orch(db, agent_client, kg, standards, intake, settings)
    img_id = orch.handle_image(sid, path, result)
    msgs = db.get_messages(sid)
    assistant_message = next((m.content for m in reversed(msgs) if m.role == "assistant"), "")
    return {"image_id": img_id, "scene": result.scene,
            "hazards": [{"object_id": h.object_id, "object_name": h.object_name, "status": h.status,
                         "hazard_type_id": h.hazard_type_id, "bbox": h.bbox,
                         "visual_evidence": h.visual_evidence} for h in result.hazards],
            "assistant_message": assistant_message}


@router.post("/sessions/{sid}/images/batch")
def upload_batch_images(
    sid: int,
    files: List[UploadFile] = File(...),
    db=Depends(deps.get_db),
    kg=Depends(deps.get_kg),
    detector=Depends(deps.get_detector),
    agent_client=Depends(deps.get_agent_client),
    intake=Depends(deps.get_intake),
    standards=Depends(deps.get_standards),
):
    if not db.session_exists(sid):
        raise HTTPException(404, "session not found")
    settings = get_settings()
    upload_dir = Path(settings.upload_dir)

    valid: list[tuple[str, str]] = []  # (original_filename, dest_path)
    failed_files: list[dict] = []

    for f in files:
        suffix = Path(f.filename or "").suffix.lower()
        if suffix not in _ALLOWED:
            failed_files.append({"filename": f.filename or "", "reason": "unsupported_type"})
            continue
        data = f.file.read(settings.max_image_bytes + 1)
        if len(data) > settings.max_image_bytes:
            failed_files.append({"filename": f.filename or "", "reason": "file_too_large"})
            continue
        try:
            path = _save_upload(data, sid, suffix, upload_dir)
        except ValueError:
            failed_files.append({"filename": f.filename or "", "reason": "invalid_path"})
            continue
        valid.append((f.filename or "", path))

    if not valid:
        raise HTTPException(422, "所有文件均无效，请检查文件类型和大小")

    def _detect_one(item: tuple[str, str]):
        filename, path = item
        try:
            return filename, path, detector.detect(path), None
        except Exception as exc:
            return filename, path, None, str(exc)

    with ThreadPoolExecutor(max_workers=settings.max_vlm_workers) as pool:
        outcomes = list(pool.map(_detect_one, valid))

    succeeded = [(path, result) for _, path, result, _ in outcomes if result is not None]
    for filename, _, result, _ in outcomes:
        if result is None:
            failed_files.append({"filename": filename, "reason": "vlm_error"})

    orch = _make_orch(db, agent_client, kg, standards, intake, settings)
    response = orch.handle_batch_images(sid, succeeded, failed_files)
    response["batch_id"] = str(uuid.uuid4())
    return response

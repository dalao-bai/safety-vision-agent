from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

import app.api.deps as deps
from app.config import get_settings
from app.agent.orchestrator import Orchestrator
from app.agent.tools import ToolContext

router = APIRouter()

_ALLOWED = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


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
    max_bytes = settings.max_image_bytes
    data = file.file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(413, "image too large")

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = (upload_dir / f"{sid}_{abs(hash(data)) % 10**10}{suffix}").resolve()
    if not dest.is_relative_to(upload_dir.resolve()):
        raise HTTPException(400, "invalid path")
    dest.write_bytes(data)

    result = detector.detect(str(dest))
    ctx_factory = lambda session_id: ToolContext(db=db, kg=kg, standards=standards, intake=intake,
                                                  report_dir=settings.report_dir, session_id=session_id)
    orch = Orchestrator(db=db, agent_client=agent_client, agent_model=settings.agent_model,
                        ctx_factory=ctx_factory, max_iterations=settings.max_tool_iterations)
    img_id = orch.handle_image(sid, str(dest), result)
    msgs = db.get_messages(sid)
    assistant_message = next((m.content for m in reversed(msgs) if m.role == "assistant"), "")
    return {"image_id": img_id, "scene": result.scene,
            "hazards": [{"object_id": h.object_id, "object_name": h.object_name, "status": h.status,
                         "hazard_type_id": h.hazard_type_id, "bbox": h.bbox,
                         "visual_evidence": h.visual_evidence} for h in result.hazards],
            "assistant_message": assistant_message}

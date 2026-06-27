from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import app.api.deps as deps
from app.agent.orchestrator import Orchestrator

router = APIRouter()


class MessageIn(BaseModel):
    text: str


@router.post("/sessions/{sid}/messages")
def post_message(sid: str, body: MessageIn,
                 db=Depends(deps.get_db),
                 orch: Orchestrator = Depends(deps.get_orchestrator)):
    if not db.session_exists(sid):
        raise HTTPException(404, "session not found")
    return {"reply": orch.handle_message(sid, body.text)}

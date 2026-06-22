from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import app.api.deps as deps
from app.config import get_settings
from app.agent.orchestrator import Orchestrator
from app.agent.tools import ToolContext

router = APIRouter()


class MessageIn(BaseModel):
    text: str


@router.post("/sessions/{sid}/messages")
def post_message(sid: int, body: MessageIn,
                 db=Depends(deps.get_db), kg=Depends(deps.get_kg),
                 agent_client=Depends(deps.get_agent_client),
                 intake=Depends(deps.get_intake),
                 standards=Depends(deps.get_standards)):
    if not db.session_exists(sid):
        raise HTTPException(404, "session not found")
    settings = get_settings()
    ctx_factory = lambda session_id: ToolContext(db=db, kg=kg, standards=standards, intake=intake,
                                                  report_dir=settings.report_dir, session_id=session_id)
    orch = Orchestrator(db=db, agent_client=agent_client, agent_model=settings.agent_model,
                        ctx_factory=ctx_factory, max_iterations=settings.max_tool_iterations)
    return {"reply": orch.handle_message(sid, body.text)}

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

import app.api.deps as deps
from app.persistence.db import Database

router = APIRouter()


@router.post("/sessions")
def create_session(db: Database = Depends(deps.get_db)):
    return {"session_id": db.create_session()}


@router.get("/sessions/{sid}")
def get_session(sid: int, db: Database = Depends(deps.get_db)):
    if not db.session_exists(sid):
        raise HTTPException(404, "session not found")
    return {"session_id": sid, "messages": [
        {"role": m.role, "content": m.content, "created_at": m.created_at}
        for m in db.get_messages(sid) if m.role != "system"]}

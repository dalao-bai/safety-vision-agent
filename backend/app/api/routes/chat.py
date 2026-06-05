"""Chat API route (U8).

The single primary conversation endpoint. Accepts a message plus an optional
image upload (multipart), runs one orchestrated agent turn, and returns the
assistant answer, conversation id, latest analysis, and tool-call summaries.

Route handlers stay thin: validate input, store the image, persist the user
message, invoke the orchestrator, map the result. All agent logic lives in
app/agent/orchestrator.py.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.agent.orchestrator import run_turn
from app.api.dependencies import (
    get_agent_client,
    get_app_settings,
    get_db,
    get_vlm_client,
)
from app.core.config import Settings
from app.db import repositories as repo
from app.models.schemas import AnalysisResult, ChatResponse
from app.services.image_storage import ImageValidationError, store_image
from app.services.responses_client import ResponsesClient

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(
    message: str = Form(...),
    conversation_id: str | None = Form(None),
    image: UploadFile | None = File(None),
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    agent_client: ResponsesClient = Depends(get_agent_client),
    vlm_client: ResponsesClient = Depends(get_vlm_client),
) -> ChatResponse:
    if not message or not message.strip():
        raise HTTPException(status_code=422, detail="message must not be empty")

    # If reusing a conversation, verify it exists before any mutation.
    if conversation_id and repo.get_conversation(conn, conversation_id) is None:
        raise HTTPException(
            status_code=404, detail=f"unknown conversation_id: {conversation_id}"
        )

    # Validate and store the image to disk BEFORE creating a conversation, so an
    # invalid image fails fast (422) without leaving an empty conversation behind.
    stored = None
    if image is not None:
        data = await image.read()
        try:
            stored = store_image(
                data,
                image.content_type or "",
                settings.upload_dir,
                settings.max_image_bytes,
            )
        except ImageValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Resolve conversation: reuse the (already-validated) id, or create a new one.
    cid = conversation_id or repo.create_conversation(conn)

    # Record the stored image's metadata now that we have a conversation.
    if stored is not None:
        repo.add_uploaded_image(
            conn,
            cid,
            stored.stored_path,
            stored.stored_filename,
            stored.mime_type,
            stored.byte_size,
        )

    # Persist the user message before running the turn so it appears in history.
    repo.add_message(conn, cid, "user", message)
    repo.touch_conversation(conn, cid)

    try:
        result = run_turn(
            conn,
            cid,
            message,
            agent_client,
            settings.agent_model,
            vlm_client,
            settings.vlm_model,
            max_iterations=settings.max_tool_iterations,
            new_image_uploaded=stored is not None,
        )
    except Exception as exc:  # noqa: BLE001 - controlled API error, audit already attempted
        raise HTTPException(
            status_code=502, detail=f"agent processing failed: {exc}"
        ) from exc

    # Latest analysis for this conversation (may predate this turn).
    raw_analysis = repo.get_latest_analysis(conn, cid)

    return ChatResponse(
        conversation_id=cid,
        answer=result.answer,
        analysis=result.analysis
        if result.analysis is not None
        else (
            None if raw_analysis is None else __import__("app.models.schemas", fromlist=["AnalysisResult"]).AnalysisResult.model_validate(raw_analysis)
        ),
        tool_calls=result.tool_calls,
    )

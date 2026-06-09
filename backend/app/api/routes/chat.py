"""Chat API route (U8 / v0.2).

The single primary conversation endpoint. Accepts a message plus an optional
image upload (multipart), runs one orchestrated agent turn, and returns the
assistant answer, conversation id, latest analysis, and tool-call summaries.

v0.2 起需登录：对话绑定 user_id 做数据隔离，并向 Agent 注入业务工具回调
（规范检索 / 报告生成），按用户隔离的历史查询与第二层偏好记忆由 orchestrator
透传 user_id 启用。

Route handlers stay thin: validate input, store the image, persist the user
message, invoke the orchestrator, map the result. All agent logic lives in
app/agent/orchestrator.py.
"""

from __future__ import annotations

import sqlite3

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
)

from app.agent.orchestrator import run_turn
from app.api.auth_deps import CurrentUser, get_current_user
from app.api.dependencies import (
    get_app_settings,
    get_db,
    get_regulation_store,
    get_vlm_client,
)

from app.api.routes.report import _run_report
from app.core.config import Settings
from app.db import repositories as repo
from app.models.schemas import AnalysisResult, ChatResponse
from app.services import report_generator as report
from app.services.image_storage import ImageValidationError, store_image
from app.services.regulation_store import RegulationStore
from app.services.responses_client import ResponsesClient

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(
    background_tasks: BackgroundTasks,
    message: str = Form(...),
    conversation_id: str | None = Form(None),
    image: UploadFile | None = File(None),
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    vlm_client: ResponsesClient = Depends(get_vlm_client),
    reg_store: RegulationStore = Depends(get_regulation_store),
    user: CurrentUser = Depends(get_current_user),
) -> ChatResponse:
    if not message or not message.strip():
        raise HTTPException(status_code=422, detail="message must not be empty")

    # If reusing a conversation, verify it exists AND belongs to this user.
    if conversation_id:
        existing = repo.get_conversation(conn, conversation_id)
        if existing is None or existing["user_id"] != user.id:
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

    # Resolve conversation: reuse the (already-validated) id, or create a new one
    # bound to the current user.
    cid = conversation_id or repo.create_conversation(conn, user_id=user.id)

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

    # 业务工具回调：规范语义检索（使用应用级单例，避免每请求重建 ChromaDB 连接）。
    def _regulation_search(query: str, top_k: int = 3) -> list[dict]:
        return reg_store.search(query, top_k=top_k)

    # 业务工具回调：报告生成（登记后台任务，返回 task_id）。
    def _report_scheduler(start: str | None, end: str | None) -> str:
        task_id = report.create_task(user.id)
        background_tasks.add_task(
            _run_report,
            task_id,
            settings.database_path,
            user.id,
            user.username,
            start,
            end,
            settings.report_dir,
        )
        return task_id

    try:
        result = run_turn(
            conn,
            cid,
            message,
            vlm_client,
            settings.vlm_model,
            settings,
            max_iterations=settings.max_tool_iterations,
            new_image_uploaded=stored is not None,
            user_id=user.id,
            regulation_search=_regulation_search,
            report_scheduler=_report_scheduler,
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
        else (None if raw_analysis is None else AnalysisResult.model_validate(raw_analysis)),
        tool_calls=result.tool_calls,
    )

"""分析确认路由 (v0.2)。

所有图片传完后，前端一次性提交逐张确认结果（准确/不准确）。本端点【不经 LLM
路由】，由前端 UI 直调，避免 LLM 状态机不可靠（审查修正项 #7）。

- 准确的图片：遍历其隐患，upsert 第三层跨对话隐患统计（user_hazard_stats）。
- 不准确的图片：整图 + 分析结果写入独立 annotation.db，供导出给标注人员。
- 全部准确 → conversations.confirmed=TRUE，触发第二层偏好更新 BackgroundTask。
- 存在不准确 → conversations.confirmed=FALSE。
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.api.auth_deps import CurrentUser, get_annotation_conn, get_current_user
from app.api.dependencies import get_app_settings, get_db
from app.core.config import Settings
from app.db import annotation as anno
from app.db import repositories as repo
from app.db.sqlite import connect
from app.models.schemas import AnalysisResult, ConfirmRequest, ConfirmResponse
from app.services.preference_updater import build_summarize_fn, update_user_preferences
from app.services.responses_client import ResponsesClient

router = APIRouter(prefix="/api/analyses", tags=["analyses"])


def _run_preference_update(
    database_path: str, user_id: str, base_url: str, api_key: str, model: str
) -> None:
    """后台任务体：用独立连接更新偏好（请求期连接此时已关闭）。失败由
    update_user_preferences 内部吞掉并保留旧值，不向上冒泡。"""
    conn = connect(database_path)
    try:
        client = ResponsesClient(base_url, api_key)
        update_user_preferences(conn, user_id, build_summarize_fn(client, model))
    finally:
        conn.close()


@router.post("/confirm", response_model=ConfirmResponse)
def confirm_analyses(
    body: ConfirmRequest,
    background_tasks: BackgroundTasks,
    conn: sqlite3.Connection = Depends(get_db),
    anno_conn: sqlite3.Connection = Depends(get_annotation_conn),
    settings: Settings = Depends(get_app_settings),
    user: CurrentUser = Depends(get_current_user),
) -> ConfirmResponse:
    """整批确认本次对话的逐张分析结果。"""
    # 校验对话归属，防止越权确认他人对话。
    conv = repo.get_conversation(conn, body.conversation_id)
    if conv is None or conv["user_id"] != user.id:
        raise HTTPException(status_code=404, detail="unknown conversation for current user")

    all_accurate = True
    annotation_created = 0

    for item in body.image_confirmations:
        # 校验图片确属本对话（conversation 已校验归属当前用户），防止携带他人
        # image_id 越权读取分析或把他人图片写入自己的标注库。
        image_row = repo.get_image_by_id(conn, item.image_id)
        if image_row is None or image_row["conversation_id"] != body.conversation_id:
            continue
        raw_analysis = repo.get_analysis_for_image(conn, item.image_id)
        if item.accurate:
            # 第三层记忆：遍历隐患做跨对话统计 upsert。
            # Validate through AnalysisResult to guard against schema drift.
            if raw_analysis:
                try:
                    validated = AnalysisResult.model_validate(raw_analysis)
                    hazards = validated.hazards
                except Exception:
                    hazards = []
                for hazard in hazards:
                    repo.upsert_hazard_stat(
                        conn, user.id, hazard.name, hazard.risk_level.value, body.conversation_id
                    )
        else:
            all_accurate = False
            # 不准确：整图写 annotation.db。image_id 重复（UNIQUE）则幂等跳过。
            try:
                anno.create_annotation_item(
                    anno_conn,
                    source_conversation_id=body.conversation_id,
                    image_id=item.image_id,
                    user_id=user.id,
                    username=user.username,
                    image_path=image_row["stored_path"],
                    image_filename=image_row["stored_filename"],
                    mime_type=image_row["mime_type"],
                    analysis=raw_analysis or {},
                )
                annotation_created += 1
            except sqlite3.IntegrityError:
                pass  # 已收集过该图，幂等跳过

    repo.set_conversation_confirmed(conn, body.conversation_id, user.id, all_accurate)

    # 全部准确才触发偏好更新（基于刚写入的统计）。
    if all_accurate and body.image_confirmations:
        background_tasks.add_task(
            _run_preference_update,
            settings.database_path,
            user.id,
            settings.openai_api_base_url,
            settings.openai_api_key,
            settings.agent_model,
        )

    return ConfirmResponse(
        conversation_id=body.conversation_id,
        confirmed=all_accurate,
        annotation_items_created=annotation_created,
    )

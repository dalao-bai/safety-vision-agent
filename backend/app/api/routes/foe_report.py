# backend/app/api/routes/foe_report.py
"""四口五临边条款报告路由（v0.3）。

POST   /api/foe/report             收新 schema 分析 → 起后台任务 → task_id
GET    /api/foe/report/status/{id} 轮询
GET    /api/foe/report/download/{id} 下载 .docx（越权校验）

本期输入来自请求体（微调模型还没接进 analyze_image）。将来分析链产出 FoeAnalysis
后，可直接复用 generate_foe_report_docx 在对话里实时出报告。
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.api.auth_deps import CurrentUser, get_current_user
from app.api.dependencies import get_app_settings, get_clause_retriever
from app.core.config import Settings
from app.models.foe_schemas import FoeAnalysis, FoeReportRequest
from app.services import foe_report_generator as foe

router = APIRouter(prefix="/api/foe/report", tags=["foe-report"])


class GenerateResponse(BaseModel):
    task_id: str


def _run_foe_report(
    task_id: str, analyses_data: list[dict], title: str | None,
    output_dir: str, image_root: str,
) -> None:
    """后台任务体：构造检索器(单例) + 渲染报告，结果写回任务表。"""
    try:
        analyses = [FoeAnalysis.model_validate(a) for a in analyses_data]
        retriever = get_clause_retriever()
        path = foe.generate_foe_report_docx(
            analyses, retriever, output_dir, title, image_root=image_root
        )
        foe.set_task_done(task_id, path)
    except Exception as exc:  # noqa: BLE001 - 失败记录给状态查询
        foe.set_task_error(task_id, str(exc))


@router.post("", response_model=GenerateResponse)
def generate(
    body: FoeReportRequest,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> GenerateResponse:
    task_id = foe.create_task(user.id)
    background_tasks.add_task(
        _run_foe_report,
        task_id,
        [a.model_dump() for a in body.analyses],
        body.title,
        settings.report_dir,
        settings.upload_dir,
    )
    return GenerateResponse(task_id=task_id)


@router.get("/status/{task_id}")
def status(task_id: str, user: CurrentUser = Depends(get_current_user)) -> dict:
    task = foe.get_task(task_id)
    if task is None or task["user_id"] != user.id:
        raise HTTPException(status_code=404, detail="unknown task_id")
    return task


@router.get("/download/{task_id}")
def download(task_id: str, user: CurrentUser = Depends(get_current_user)) -> FileResponse:
    task = foe.get_task(task_id)
    if task is None or task["user_id"] != user.id:
        raise HTTPException(status_code=404, detail="unknown task_id")
    if task["status"] != "done":
        raise HTTPException(status_code=409, detail=f"report not ready: {task['status']}")
    return FileResponse(
        task["path"],
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"foe_report_{task_id}.docx",
    )

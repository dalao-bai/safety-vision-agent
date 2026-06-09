"""合规报告生成路由（任务 C）。

提供后台异步生成 .docx 报告的三段式接口：
- POST /api/report/generate    登记后台任务，立即返回 task_id
- GET  /api/report/status/{id} 轮询任务状态
- GET  /api/report/download/{id} 下载生成的 .docx（带越权校验）

报告生成本身放在 FastAPI BackgroundTasks 里执行，避免阻塞请求。所有接口
都要求登录（get_current_user），下载时额外校验任务归属。
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.api.auth_deps import CurrentUser, get_current_user
from app.api.dependencies import get_app_settings, get_db
from app.core.config import Settings
from app.services import report_generator as report

router = APIRouter(prefix="/api/report", tags=["report"])


class GenerateRequest(BaseModel):
    """报告生成请求：时间区间均可选，None 表示不限。"""

    start_date: str | None = None
    end_date: str | None = None


class GenerateResponse(BaseModel):
    task_id: str


def _run_report(
    task_id: str,
    db_path: str,
    user_id: str,
    username: str,
    start: str | None,
    end: str | None,
    output_dir: str,
) -> None:
    """后台任务体：独立开库连接生成报告，结果写回任务注册表。

    BackgroundTasks 在请求结束后运行，请求期的连接此时已关闭，故这里
    用 db_path 自建一条连接。
    """
    from app.db.sqlite import connect, init_db

    conn = connect(db_path)
    init_db(conn)
    try:
        path = report.generate_report_docx(
            conn, user_id, username, start, end, output_dir
        )
        report.set_task_done(task_id, path)
    except Exception as exc:  # noqa: BLE001 - 后台任务失败需记录给状态查询
        report.set_task_error(task_id, str(exc))
    finally:
        conn.close()


@router.post("/generate", response_model=GenerateResponse)
def generate(
    body: GenerateRequest,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> GenerateResponse:
    task_id = report.create_task(user.id)
    background_tasks.add_task(
        _run_report,
        task_id,
        settings.database_path,
        user.id,
        user.username,
        body.start_date,
        body.end_date,
        settings.report_dir,
    )
    return GenerateResponse(task_id=task_id)


@router.get("/status/{task_id}")
def status(
    task_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    task = report.get_task(task_id)
    if task is None or task["user_id"] != user.id:
        # 不区分"不存在"与"非本人"，避免泄露他人 task_id 的存在性。
        raise HTTPException(status_code=404, detail="unknown task_id")
    return task


@router.get("/download/{task_id}")
def download(
    task_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> FileResponse:
    task = report.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="unknown task_id")
    if task["user_id"] != user.id:
        raise HTTPException(status_code=403, detail="not your report")
    if task["status"] != "done":
        raise HTTPException(status_code=409, detail=f"report not ready: {task['status']}")
    return FileResponse(
        task["path"],
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"compliance_report_{task_id}.docx",
    )

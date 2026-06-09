"""待标注导出路由（任务 E）。

GET ""        → 当前用户的全部标注记录（JSON，供前端预览）。
GET "/export" → 当前用户【未导出】的标注记录导出为 CSV，并标记为已导出。

所有查询均带 user_id 过滤（list_annotation_items / mark_exported 内部强制），
防止越权。
"""

from __future__ import annotations

import csv
import io
import sqlite3

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.auth_deps import CurrentUser, get_annotation_conn, get_current_user
from app.db import annotation as anno

router = APIRouter(prefix="/api/annotation", tags=["annotation"])

_CSV_COLUMNS = [
    "id",
    "source_conversation_id",
    "image_id",
    "image_filename",
    "mime_type",
    "error_type",
    "created_at",
    "analysis_summary",
]


@router.get("")
def list_items(
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_annotation_conn),
) -> dict:
    """返回当前用户的全部标注记录（JSON 列表）。"""
    return {"items": anno.list_annotation_items(conn, user.id)}


@router.get("/export")
def export_items(
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_annotation_conn),
) -> StreamingResponse:
    """导出当前用户未导出的标注记录为 CSV，并将其标记为已导出。"""
    items = anno.list_annotation_items(conn, user.id, exported=False)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_CSV_COLUMNS)
    for item in items:
        analysis = item.get("analysis_json") or {}
        summary = analysis.get("summary", "") if isinstance(analysis, dict) else ""
        writer.writerow([
            item["id"],
            item["source_conversation_id"],
            item["image_id"],
            item["image_filename"],
            item["mime_type"],
            item.get("error_type") or "",
            item["created_at"],
            summary,
        ])

    # 导出成功后标记，避免重复导出。
    anno.mark_exported(conn, [item["id"] for item in items], user.id)

    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=annotation_export.csv"},
    )

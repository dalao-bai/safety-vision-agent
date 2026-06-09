"""历史查询路由（任务 E）。

只读：返回当前用户在可选时间段内的对话列表与隐患统计。所有查询均带
user_id 过滤，防止越权。对话与统计逻辑分别复用 repositories 中的
list_conversations_by_user / get_hazard_stats_by_user。
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from app.api.auth_deps import CurrentUser, get_current_user
from app.api.dependencies import get_db
from app.db import repositories as repo

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("")
def get_history(
    start: str | None = None,
    end: str | None = None,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """返回当前用户的对话列表与隐患统计。

    start / end 为可选 ISO-8601 时间字符串，按对话 created_at 过滤。
    """
    conversations = repo.list_conversations_by_user(conn, user.id, start=start, end=end)
    hazard_stats = repo.get_hazard_stats_by_user(conn, user.id)
    return {
        "conversations": [dict(row) for row in conversations],
        "hazard_stats": hazard_stats,
    }

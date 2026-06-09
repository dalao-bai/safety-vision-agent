"""annotation.db — 待标注图片库（独立 SQLite，图片粒度）。

与主库完全隔离：使用独立连接函数，不共享 sqlite.py 的 schema 初始化。
所有查询均携带 user_id 过滤，防止越权。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ANNOTATION_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS annotation_items (
    id                     TEXT    PRIMARY KEY,      -- uuid4
    source_conversation_id TEXT    NOT NULL,
    image_id               INTEGER NOT NULL,
    user_id                TEXT    NOT NULL,
    username               TEXT    NOT NULL,
    image_path             TEXT    NOT NULL,
    image_filename         TEXT    NOT NULL,
    mime_type              TEXT    NOT NULL,
    analysis_json          TEXT    NOT NULL,         -- 序列化的分析结果
    error_type             TEXT,                     -- 标注的错误类型，NULL 表示准确
    created_at             TEXT    NOT NULL,
    exported_at            TEXT,                     -- NULL 表示未导出
    UNIQUE (image_id)
);

CREATE INDEX IF NOT EXISTS idx_annotation_user     ON annotation_items(user_id);
CREATE INDEX IF NOT EXISTS idx_annotation_exported ON annotation_items(exported_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dumps(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _loads(value: str | None) -> Any:
    if value is None:
        return None
    return json.loads(value)


def connect_annotation(db_path: str) -> sqlite3.Connection:
    """打开 annotation.db 连接并初始化 schema（幂等）。"""
    path = Path(db_path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_ANNOTATION_SCHEMA)
    conn.commit()
    return conn


# --- CRUD ------------------------------------------------------------------

def create_annotation_item(
    conn: sqlite3.Connection,
    source_conversation_id: str,
    image_id: int,
    user_id: str,
    username: str,
    image_path: str,
    image_filename: str,
    mime_type: str,
    analysis: dict[str, Any],
) -> str:
    """插入一条标注记录，返回 id。image_id 重复时抛 IntegrityError（UNIQUE 约束）。"""
    aid = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO annotation_items
            (id, source_conversation_id, image_id, user_id, username,
             image_path, image_filename, mime_type, analysis_json,
             error_type, created_at, exported_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL)
        """,
        (
            aid,
            source_conversation_id,
            image_id,
            user_id,
            username,
            image_path,
            image_filename,
            mime_type,
            _dumps(analysis),
            _now(),
        ),
    )
    conn.commit()
    return aid


def get_annotation_item(
    conn: sqlite3.Connection, item_id: str, user_id: str
) -> dict[str, Any] | None:
    """按 id 查询，强制 user_id 过滤防止越权。"""
    row = conn.execute(
        "SELECT * FROM annotation_items WHERE id = ? AND user_id = ?",
        (item_id, user_id),
    ).fetchone()
    if row is None:
        return None
    return _row_to_dict(row)


def list_annotation_items(
    conn: sqlite3.Connection,
    user_id: str,
    exported: bool | None = None,
) -> list[dict[str, Any]]:
    """列出当前用户的标注记录。exported=True/False 过滤导出状态，None 不过滤。"""
    sql = "SELECT * FROM annotation_items WHERE user_id = ?"
    params: list = [user_id]
    if exported is True:
        sql += " AND exported_at IS NOT NULL"
    elif exported is False:
        sql += " AND exported_at IS NULL"
    sql += " ORDER BY created_at ASC"
    cur = conn.execute(sql, params)
    return [_row_to_dict(r) for r in cur.fetchall()]


def mark_exported(
    conn: sqlite3.Connection, item_ids: list[str], user_id: str
) -> int:
    """批量标记已导出；user_id 校验防止越权。返回实际更新行数。"""
    if not item_ids:
        return 0
    now = _now()
    placeholders = ",".join("?" * len(item_ids))
    cur = conn.execute(
        f"UPDATE annotation_items SET exported_at = ? "
        f"WHERE id IN ({placeholders}) AND user_id = ? AND exported_at IS NULL",
        [now, *item_ids, user_id],
    )
    conn.commit()
    return cur.rowcount


def set_error_type(
    conn: sqlite3.Connection, item_id: str, user_id: str, error_type: str | None
) -> bool:
    """更新标注错误类型（NULL 表示标注为准确）；user_id 校验防越权。"""
    cur = conn.execute(
        "UPDATE annotation_items SET error_type = ? WHERE id = ? AND user_id = ?",
        (error_type, item_id, user_id),
    )
    conn.commit()
    return cur.rowcount > 0


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["analysis_json"] = _loads(item["analysis_json"])
    return item

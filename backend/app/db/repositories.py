"""Repository functions for v0.1 audit entities (U2).

Small explicit functions per aggregate. No ORM. JSON payloads are serialized to
text columns at this boundary so callers work with Python objects.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any


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


# --- conversations ---------------------------------------------------------

def create_conversation(conn: sqlite3.Connection, conversation_id: str | None = None) -> str:
    """Create a conversation and return its id. Generates a UUID if none given."""
    cid = conversation_id or str(uuid.uuid4())
    now = _now()
    conn.execute(
        "INSERT INTO conversations (id, created_at, updated_at) VALUES (?, ?, ?)",
        (cid, now, now),
    )
    conn.commit()
    return cid


def get_conversation(conn: sqlite3.Connection, conversation_id: str) -> sqlite3.Row | None:
    cur = conn.execute(
        "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
    )
    return cur.fetchone()


def touch_conversation(conn: sqlite3.Connection, conversation_id: str) -> None:
    """Update the conversation's updated_at timestamp."""
    conn.execute(
        "UPDATE conversations SET updated_at = ? WHERE id = ?",
        (_now(), conversation_id),
    )
    conn.commit()


# --- messages --------------------------------------------------------------

def add_message(
    conn: sqlite3.Connection, conversation_id: str, role: str, content: str
) -> int:
    cur = conn.execute(
        "INSERT INTO messages (conversation_id, role, content, created_at) "
        "VALUES (?, ?, ?, ?)",
        (conversation_id, role, content, _now()),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_messages(conn: sqlite3.Connection, conversation_id: str) -> list[sqlite3.Row]:
    cur = conn.execute(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id ASC",
        (conversation_id,),
    )
    return cur.fetchall()


# --- uploaded images -------------------------------------------------------

def add_uploaded_image(
    conn: sqlite3.Connection,
    conversation_id: str,
    stored_path: str,
    stored_filename: str,
    mime_type: str,
    byte_size: int,
) -> int:
    cur = conn.execute(
        "INSERT INTO uploaded_images "
        "(conversation_id, stored_path, stored_filename, mime_type, byte_size, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (conversation_id, stored_path, stored_filename, mime_type, byte_size, _now()),
    )
    conn.commit()
    return int(cur.lastrowid)


def get_latest_image(conn: sqlite3.Connection, conversation_id: str) -> sqlite3.Row | None:
    cur = conn.execute(
        "SELECT * FROM uploaded_images WHERE conversation_id = ? ORDER BY id DESC LIMIT 1",
        (conversation_id,),
    )
    return cur.fetchone()


# --- analysis results ------------------------------------------------------

def save_analysis_result(
    conn: sqlite3.Connection,
    conversation_id: str,
    result: dict[str, Any],
    image_id: int | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO analysis_results (conversation_id, image_id, result_json, created_at) "
        "VALUES (?, ?, ?, ?)",
        (conversation_id, image_id, _dumps(result), _now()),
    )
    conn.commit()
    return int(cur.lastrowid)


def get_latest_analysis(conn: sqlite3.Connection, conversation_id: str) -> dict[str, Any] | None:
    cur = conn.execute(
        "SELECT result_json FROM analysis_results WHERE conversation_id = ? "
        "ORDER BY id DESC LIMIT 1",
        (conversation_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return _loads(row["result_json"])


# --- tool calls ------------------------------------------------------------

def save_tool_call(
    conn: sqlite3.Connection,
    conversation_id: str,
    tool_name: str,
    status: str,
    input_data: Any = None,
    output_data: Any = None,
    error: str | None = None,
    duration_ms: int | None = None,
    call_id: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO tool_calls "
        "(conversation_id, call_id, tool_name, input_json, output_json, status, error, duration_ms, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            conversation_id,
            call_id,
            tool_name,
            _dumps(input_data),
            _dumps(output_data),
            status,
            error,
            duration_ms,
            _now(),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_tool_calls(conn: sqlite3.Connection, conversation_id: str) -> list[dict[str, Any]]:
    cur = conn.execute(
        "SELECT * FROM tool_calls WHERE conversation_id = ? ORDER BY id ASC",
        (conversation_id,),
    )
    rows = cur.fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["input_json"] = _loads(item["input_json"])
        item["output_json"] = _loads(item["output_json"])
        result.append(item)
    return result


# --- model responses -------------------------------------------------------

def save_model_response(
    conn: sqlite3.Connection,
    conversation_id: str,
    model_role: str,
    status: str,
    provider_id: str | None = None,
    raw_text: str | None = None,
    error: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO model_responses "
        "(conversation_id, model_role, provider_id, status, raw_text, error, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (conversation_id, model_role, provider_id, status, raw_text, error, _now()),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_model_responses(conn: sqlite3.Connection, conversation_id: str) -> list[sqlite3.Row]:
    cur = conn.execute(
        "SELECT * FROM model_responses WHERE conversation_id = ? ORDER BY id ASC",
        (conversation_id,),
    )
    return cur.fetchall()


# ============================================================
# v0.2 新增：users
# ============================================================

def create_user(conn: sqlite3.Connection, username: str, api_key_hash: str) -> str:
    """创建用户，返回新用户 id（uuid4）。username 重复时抛 IntegrityError。"""
    uid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO users (id, username, api_key_hash, created_at) VALUES (?, ?, ?, ?)",
        (uid, username, api_key_hash, _now()),
    )
    conn.commit()
    return uid


def get_user_by_username(conn: sqlite3.Connection, username: str) -> sqlite3.Row | None:
    cur = conn.execute("SELECT * FROM users WHERE username = ?", (username,))
    return cur.fetchone()


def get_user_by_id(conn: sqlite3.Connection, user_id: str) -> sqlite3.Row | None:
    cur = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    return cur.fetchone()


# ============================================================
# v0.2 新增：user_preferences
# ============================================================

def get_preferences(conn: sqlite3.Connection, user_id: str) -> dict[str, Any] | None:
    cur = conn.execute(
        "SELECT * FROM user_preferences WHERE user_id = ?", (user_id,)
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {
        "user_id": row["user_id"],
        "preference_summary": row["preference_summary"],
        "focus_hazard_types": _loads(row["focus_hazard_types"]),
        "frequent_questions": _loads(row["frequent_questions"]),
        "updated_at": row["updated_at"],
    }


def upsert_preferences(
    conn: sqlite3.Connection,
    user_id: str,
    preference_summary: str | None = None,
    focus_hazard_types: list | None = None,
    frequent_questions: list | None = None,
) -> None:
    """INSERT OR REPLACE 整行；调用方只传想更新的字段，未传字段保持原值。"""
    existing = get_preferences(conn, user_id)
    summary = preference_summary if preference_summary is not None else (
        existing["preference_summary"] if existing else None
    )
    types_ = focus_hazard_types if focus_hazard_types is not None else (
        existing["focus_hazard_types"] if existing else []
    )
    questions = frequent_questions if frequent_questions is not None else (
        existing["frequent_questions"] if existing else []
    )
    conn.execute(
        """
        INSERT INTO user_preferences
            (user_id, preference_summary, focus_hazard_types, frequent_questions, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            preference_summary  = excluded.preference_summary,
            focus_hazard_types  = excluded.focus_hazard_types,
            frequent_questions  = excluded.frequent_questions,
            updated_at          = excluded.updated_at
        """,
        (user_id, summary, _dumps(types_), _dumps(questions), _now()),
    )
    conn.commit()


# ============================================================
# v0.2 新增：user_hazard_stats
# ============================================================

def upsert_hazard_stat(
    conn: sqlite3.Connection,
    user_id: str,
    hazard_type: str,
    risk_level: str,
    conversation_id: str,
) -> None:
    """(user_id, hazard_type, risk_level) 存在则 +1 并追加 conversation_id，否则插入。"""
    row = conn.execute(
        "SELECT id, occurrence_count, conversation_ids FROM user_hazard_stats "
        "WHERE user_id = ? AND hazard_type = ? AND risk_level = ?",
        (user_id, hazard_type, risk_level),
    ).fetchone()

    now = _now()
    if row is None:
        conn.execute(
            "INSERT INTO user_hazard_stats "
            "(user_id, hazard_type, risk_level, occurrence_count, last_seen_at, conversation_ids) "
            "VALUES (?, ?, ?, 1, ?, ?)",
            (user_id, hazard_type, risk_level, now, _dumps([conversation_id])),
        )
    else:
        ids: list = _loads(row["conversation_ids"]) or []
        if conversation_id not in ids:
            ids.append(conversation_id)
        conn.execute(
            "UPDATE user_hazard_stats SET "
            "occurrence_count = ?, last_seen_at = ?, conversation_ids = ? "
            "WHERE id = ?",
            (row["occurrence_count"] + 1, now, _dumps(ids), row["id"]),
        )
    conn.commit()


def get_hazard_stats_by_user(
    conn: sqlite3.Connection, user_id: str
) -> list[dict[str, Any]]:
    cur = conn.execute(
        "SELECT * FROM user_hazard_stats WHERE user_id = ? ORDER BY occurrence_count DESC",
        (user_id,),
    )
    result = []
    for row in cur.fetchall():
        item = dict(row)
        item["conversation_ids"] = _loads(item["conversation_ids"])
        result.append(item)
    return result


# ============================================================
# v0.2 新增：regulation_files
# ============================================================

def create_regulation_file(
    conn: sqlite3.Connection,
    filename: str,
    original_name: str,
    file_path: str,
    file_type: str,
    chunk_count: int = 0,
) -> str:
    """注册规范文件元数据，返回 id（uuid4）。"""
    fid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO regulation_files "
        "(id, filename, original_name, file_path, file_type, chunk_count, deleted_at, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, NULL, ?)",
        (fid, filename, original_name, file_path, file_type, chunk_count, _now()),
    )
    conn.commit()
    return fid


def list_regulation_files(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """返回未软删除的规范文件列表，按创建时间降序。"""
    cur = conn.execute(
        "SELECT * FROM regulation_files WHERE deleted_at IS NULL ORDER BY created_at DESC"
    )
    return cur.fetchall()


def soft_delete_regulation_file(conn: sqlite3.Connection, file_id: str) -> bool:
    """软删除，返回 True 表示找到并标记；False 表示记录不存在或已删除。"""
    cur = conn.execute(
        "UPDATE regulation_files SET deleted_at = ? "
        "WHERE id = ? AND deleted_at IS NULL",
        (_now(), file_id),
    )
    conn.commit()
    return cur.rowcount > 0


# ============================================================
# v0.2 新增：conversations 含 user_id 的创建和查询
# 注意：覆盖 v0.1 的 create_conversation，保持向后兼容（user_id 可选）
# ============================================================

def create_conversation(
    conn: sqlite3.Connection,
    conversation_id: str | None = None,
    user_id: str | None = None,
) -> str:
    """创建对话，支持可选的 user_id 绑定。覆盖 v0.1 同名函数，向后兼容。"""
    cid = conversation_id or str(uuid.uuid4())
    now = _now()
    conn.execute(
        "INSERT INTO conversations (id, user_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (cid, user_id, now, now),
    )
    conn.commit()
    return cid


def list_conversations_by_user(
    conn: sqlite3.Connection,
    user_id: str,
    start: str | None = None,
    end: str | None = None,
) -> list[sqlite3.Row]:
    """返回用户在时间范围内的对话列表（用于 /api/history）。

    start / end 为 ISO-8601 字符串，均为可选。
    """
    sql = "SELECT * FROM conversations WHERE user_id = ?"
    params: list = [user_id]
    if start:
        sql += " AND created_at >= ?"
        params.append(start)
    if end:
        sql += " AND created_at <= ?"
        params.append(end)
    sql += " ORDER BY created_at DESC"
    cur = conn.execute(sql, params)
    return cur.fetchall()


def set_conversation_confirmed(
    conn: sqlite3.Connection,
    conversation_id: str,
    user_id: str,
    confirmed: bool,
) -> bool:
    """更新确认状态；user_id 校验防止越权。返回 True 表示更新成功。"""
    cur = conn.execute(
        "UPDATE conversations SET confirmed = ? WHERE id = ? AND user_id = ?",
        (1 if confirmed else 0, conversation_id, user_id),
    )
    conn.commit()
    return cur.rowcount > 0


# ============================================================
# v0.2 新增：跨对话读取助手（报告生成 / 历史查询 / 确认流程依赖）
# ============================================================

def get_image_by_id(conn: sqlite3.Connection, image_id: int) -> sqlite3.Row | None:
    """按主键查单张图片元数据（确认流程写 annotation.db 时需要）。"""
    cur = conn.execute(
        "SELECT * FROM uploaded_images WHERE id = ?", (image_id,)
    )
    return cur.fetchone()


def list_images(conn: sqlite3.Connection, conversation_id: str) -> list[sqlite3.Row]:
    """按上传顺序返回某对话的全部图片（报告嵌图、确认流程逐张遍历）。"""
    cur = conn.execute(
        "SELECT * FROM uploaded_images WHERE conversation_id = ? ORDER BY id ASC",
        (conversation_id,),
    )
    return cur.fetchall()


def list_analysis_results(
    conn: sqlite3.Connection, conversation_id: str
) -> list[dict[str, Any]]:
    """返回某对话的全部分析结果（已反序列化），按时间顺序。

    每项形如 {"id", "image_id", "result", "created_at"}，其中 result 为
    反序列化后的 AnalysisResult dict。
    """
    cur = conn.execute(
        "SELECT id, image_id, result_json, created_at FROM analysis_results "
        "WHERE conversation_id = ? ORDER BY id ASC",
        (conversation_id,),
    )
    out: list[dict[str, Any]] = []
    for row in cur.fetchall():
        out.append({
            "id": row["id"],
            "image_id": row["image_id"],
            "result": _loads(row["result_json"]),
            "created_at": row["created_at"],
        })
    return out


def get_analysis_for_image(
    conn: sqlite3.Connection, image_id: int
) -> dict[str, Any] | None:
    """返回某张图片最近一次分析结果（已反序列化），无则 None。"""
    cur = conn.execute(
        "SELECT result_json FROM analysis_results WHERE image_id = ? "
        "ORDER BY id DESC LIMIT 1",
        (image_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return _loads(row["result_json"])

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

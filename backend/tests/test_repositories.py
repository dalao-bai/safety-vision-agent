"""Tests for the SQLite repository layer (U2)."""

from __future__ import annotations

import sqlite3

import pytest

from app.db import repositories as repo
from app.db.sqlite import connect, init_db


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "test.db"
    connection = connect(str(db_path))
    init_db(connection)
    yield connection
    connection.close()


def test_init_creates_all_tables(conn):
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row["name"] for row in cur.fetchall()}
    assert {
        "conversations",
        "messages",
        "uploaded_images",
        "analysis_results",
        "tool_calls",
        "model_responses",
    }.issubset(tables)


def test_conversation_and_messages_in_chronological_order(conn):
    cid = repo.create_conversation(conn)
    repo.add_message(conn, cid, "user", "第一条")
    repo.add_message(conn, cid, "assistant", "第二条")
    repo.add_message(conn, cid, "user", "第三条")

    messages = repo.list_messages(conn, cid)
    assert [m["content"] for m in messages] == ["第一条", "第二条", "第三条"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]


def test_uploaded_image_links_to_conversation(conn):
    cid = repo.create_conversation(conn)
    image_id = repo.add_uploaded_image(
        conn, cid, "runtime/uploads/abc.jpg", "abc.jpg", "image/jpeg", 12345
    )

    latest = repo.get_latest_image(conn, cid)
    assert latest is not None
    assert latest["id"] == image_id
    assert latest["mime_type"] == "image/jpeg"
    assert latest["byte_size"] == 12345


def test_analysis_result_preserves_structured_json(conn):
    cid = repo.create_conversation(conn)
    result = {
        "summary": "存在高空作业隐患",
        "hazards": [
            {
                "name": "未系安全带",
                "location": "脚手架顶部",
                "risk_level": "high",
                "basis": "工人在高处无防护",
                "remediation": "立即佩戴安全带",
                "confidence": 0.9,
            }
        ],
        "needs_followup": False,
        "followup_question": None,
    }
    repo.save_analysis_result(conn, cid, result)

    loaded = repo.get_latest_analysis(conn, cid)
    assert loaded == result
    # Ensure Chinese text round-trips without escaping corruption.
    assert loaded["hazards"][0]["name"] == "未系安全带"


def test_latest_analysis_returns_most_recent(conn):
    cid = repo.create_conversation(conn)
    repo.save_analysis_result(conn, cid, {"summary": "first", "hazards": []})
    repo.save_analysis_result(conn, cid, {"summary": "second", "hazards": []})

    loaded = repo.get_latest_analysis(conn, cid)
    assert loaded["summary"] == "second"


def test_tool_call_preserves_status_and_payloads(conn):
    cid = repo.create_conversation(conn)
    repo.save_tool_call(
        conn,
        cid,
        tool_name="rank_risks",
        status="success",
        input_data={"scope": "all"},
        output_data={"ranked": ["a", "b"]},
        duration_ms=42,
        call_id="call_abc",
    )

    calls = repo.list_tool_calls(conn, cid)
    assert len(calls) == 1
    assert calls[0]["tool_name"] == "rank_risks"
    assert calls[0]["status"] == "success"
    assert calls[0]["input_json"] == {"scope": "all"}
    assert calls[0]["output_json"] == {"ranked": ["a", "b"]}
    assert calls[0]["duration_ms"] == 42
    # call_id links the tool call to the Agent response that requested it.
    assert calls[0]["call_id"] == "call_abc"


def test_model_response_preserves_raw_payload(conn):
    cid = repo.create_conversation(conn)
    repo.save_model_response(
        conn,
        cid,
        model_role="vlm",
        status="success",
        provider_id="resp_123",
        raw_text='{"summary": "ok"}',
    )

    rows = repo.list_model_responses(conn, cid)
    assert len(rows) == 1
    assert rows[0]["model_role"] == "vlm"
    assert rows[0]["provider_id"] == "resp_123"
    assert rows[0]["raw_text"] == '{"summary": "ok"}'


def test_model_response_records_error(conn):
    cid = repo.create_conversation(conn)
    repo.save_model_response(
        conn, cid, model_role="agent", status="error", error="timeout"
    )

    rows = repo.list_model_responses(conn, cid)
    assert rows[0]["status"] == "error"
    assert rows[0]["error"] == "timeout"


def test_foreign_key_rejects_orphan_message(conn):
    # No conversation created; inserting a message must fail rather than orphan.
    with pytest.raises(sqlite3.IntegrityError):
        repo.add_message(conn, "nonexistent-cid", "user", "orphan")

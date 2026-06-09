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


# ============================================================
# v0.2 新增测试
# ============================================================

# --- users -----------------------------------------------------------------

def test_create_and_get_user(conn):
    uid = repo.create_user(conn, "alice", "hashed_key_abc")
    row = repo.get_user_by_username(conn, "alice")
    assert row is not None
    assert row["id"] == uid
    assert row["api_key_hash"] == "hashed_key_abc"


def test_get_user_by_id(conn):
    uid = repo.create_user(conn, "bob", "hash_bob")
    row = repo.get_user_by_id(conn, uid)
    assert row is not None
    assert row["username"] == "bob"


def test_get_user_nonexistent(conn):
    assert repo.get_user_by_username(conn, "nobody") is None
    assert repo.get_user_by_id(conn, "nonexistent-id") is None


def test_duplicate_username_raises(conn):
    repo.create_user(conn, "carol", "h1")
    with pytest.raises(sqlite3.IntegrityError):
        repo.create_user(conn, "carol", "h2")


# --- user_preferences ------------------------------------------------------

def test_upsert_and_get_preferences(conn):
    uid = repo.create_user(conn, "dave", "h")
    repo.upsert_preferences(
        conn, uid,
        preference_summary="关注高处作业",
        focus_hazard_types=["高处坠落", "物体打击"],
        frequent_questions=["安全带标准是什么"],
    )
    prefs = repo.get_preferences(conn, uid)
    assert prefs is not None
    assert prefs["preference_summary"] == "关注高处作业"
    assert prefs["focus_hazard_types"] == ["高处坠落", "物体打击"]
    assert prefs["frequent_questions"] == ["安全带标准是什么"]


def test_upsert_preferences_is_idempotent(conn):
    uid = repo.create_user(conn, "eve", "h")
    repo.upsert_preferences(conn, uid, preference_summary="v1")
    repo.upsert_preferences(conn, uid, preference_summary="v2")
    prefs = repo.get_preferences(conn, uid)
    assert prefs["preference_summary"] == "v2"


def test_get_preferences_nonexistent(conn):
    uid = repo.create_user(conn, "frank", "h")
    assert repo.get_preferences(conn, uid) is None


def test_upsert_preserves_unset_fields(conn):
    uid = repo.create_user(conn, "grace", "h")
    repo.upsert_preferences(conn, uid, focus_hazard_types=["触电"])
    # 只更新 summary，不传 focus_hazard_types，原值应保留
    repo.upsert_preferences(conn, uid, preference_summary="新摘要")
    prefs = repo.get_preferences(conn, uid)
    assert prefs["focus_hazard_types"] == ["触电"]
    assert prefs["preference_summary"] == "新摘要"


# --- user_hazard_stats -----------------------------------------------------

def test_upsert_hazard_stat_creates_new(conn):
    uid = repo.create_user(conn, "hank", "h")
    cid = repo.create_conversation(conn, user_id=uid)
    repo.upsert_hazard_stat(conn, uid, "高处坠落", "high", cid)
    stats = repo.get_hazard_stats_by_user(conn, uid)
    assert len(stats) == 1
    assert stats[0]["hazard_type"] == "高处坠落"
    assert stats[0]["occurrence_count"] == 1
    assert cid in stats[0]["conversation_ids"]


def test_upsert_hazard_stat_increments_count(conn):
    uid = repo.create_user(conn, "ivan", "h")
    cid1 = repo.create_conversation(conn, user_id=uid)
    cid2 = repo.create_conversation(conn, user_id=uid)
    repo.upsert_hazard_stat(conn, uid, "触电", "medium", cid1)
    repo.upsert_hazard_stat(conn, uid, "触电", "medium", cid2)
    stats = repo.get_hazard_stats_by_user(conn, uid)
    assert stats[0]["occurrence_count"] == 2
    assert set(stats[0]["conversation_ids"]) == {cid1, cid2}


def test_upsert_hazard_stat_deduplicates_conversation_id(conn):
    uid = repo.create_user(conn, "judy", "h")
    cid = repo.create_conversation(conn, user_id=uid)
    repo.upsert_hazard_stat(conn, uid, "物体打击", "low", cid)
    repo.upsert_hazard_stat(conn, uid, "物体打击", "low", cid)  # 同一 cid 不重复追加
    stats = repo.get_hazard_stats_by_user(conn, uid)
    assert stats[0]["conversation_ids"].count(cid) == 1


def test_hazard_stats_isolated_by_user(conn):
    uid1 = repo.create_user(conn, "user1", "h")
    uid2 = repo.create_user(conn, "user2", "h")
    cid1 = repo.create_conversation(conn, user_id=uid1)
    cid2 = repo.create_conversation(conn, user_id=uid2)
    repo.upsert_hazard_stat(conn, uid1, "高处坠落", "high", cid1)
    repo.upsert_hazard_stat(conn, uid2, "触电", "medium", cid2)
    assert len(repo.get_hazard_stats_by_user(conn, uid1)) == 1
    assert repo.get_hazard_stats_by_user(conn, uid1)[0]["hazard_type"] == "高处坠落"
    assert len(repo.get_hazard_stats_by_user(conn, uid2)) == 1


# --- regulation_files -------------------------------------------------------

def test_create_and_list_regulation_files(conn):
    fid = repo.create_regulation_file(
        conn, "abc.pdf", "施工规范.pdf", "/runtime/regs/abc.pdf", "pdf", 42
    )
    files = repo.list_regulation_files(conn)
    assert len(files) == 1
    assert files[0]["id"] == fid
    assert files[0]["original_name"] == "施工规范.pdf"
    assert files[0]["chunk_count"] == 42


def test_soft_delete_hides_from_list(conn):
    fid = repo.create_regulation_file(
        conn, "b.docx", "规程.docx", "/runtime/regs/b.docx", "docx"
    )
    assert len(repo.list_regulation_files(conn)) == 1
    result = repo.soft_delete_regulation_file(conn, fid)
    assert result is True
    assert len(repo.list_regulation_files(conn)) == 0


def test_soft_delete_nonexistent_returns_false(conn):
    assert repo.soft_delete_regulation_file(conn, "no-such-id") is False


def test_soft_delete_twice_returns_false(conn):
    fid = repo.create_regulation_file(
        conn, "c.pdf", "c.pdf", "/runtime/regs/c.pdf", "pdf"
    )
    assert repo.soft_delete_regulation_file(conn, fid) is True
    assert repo.soft_delete_regulation_file(conn, fid) is False


# --- conversations v0.2 扩展 -----------------------------------------------

def test_create_conversation_with_user_id(conn):
    uid = repo.create_user(conn, "lena", "h")
    cid = repo.create_conversation(conn, user_id=uid)
    row = repo.get_conversation(conn, cid)
    assert row["user_id"] == uid


def test_list_conversations_by_user_filters_correctly(conn):
    uid1 = repo.create_user(conn, "mike", "h")
    uid2 = repo.create_user(conn, "nina", "h")
    cid1 = repo.create_conversation(conn, user_id=uid1)
    repo.create_conversation(conn, user_id=uid2)
    result = repo.list_conversations_by_user(conn, uid1)
    assert len(result) == 1
    assert result[0]["id"] == cid1


def test_list_conversations_time_range(conn):
    uid = repo.create_user(conn, "omar", "h")
    repo.create_conversation(conn, user_id=uid)
    convs = repo.list_conversations_by_user(conn, uid, start="2000-01-01", end="2099-12-31")
    assert len(convs) == 1
    convs_empty = repo.list_conversations_by_user(conn, uid, start="2099-01-01")
    assert len(convs_empty) == 0


def test_set_conversation_confirmed(conn):
    uid = repo.create_user(conn, "pat", "h")
    cid = repo.create_conversation(conn, user_id=uid)
    ok = repo.set_conversation_confirmed(conn, cid, uid, True)
    assert ok is True
    row = repo.get_conversation(conn, cid)
    assert row["confirmed"] == 1


def test_set_conversation_confirmed_wrong_user(conn):
    uid1 = repo.create_user(conn, "quinn", "h")
    uid2 = repo.create_user(conn, "rosa", "h")
    cid = repo.create_conversation(conn, user_id=uid1)
    ok = repo.set_conversation_confirmed(conn, cid, uid2, True)  # 越权
    assert ok is False


def test_create_conversation_backward_compatible(conn):
    """不传 user_id 时仍然正常工作（v0.1 兼容性）。"""
    cid = repo.create_conversation(conn)
    row = repo.get_conversation(conn, cid)
    assert row is not None
    assert row["user_id"] is None

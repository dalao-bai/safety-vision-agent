"""Tests for conversation context assembly (v0.2 / LangGraph).

Verifies that build_context returns a list[BaseMessage] and injects an explicit
analyze_image instruction when an image was uploaded this turn — the agent model
only sees text and otherwise has no way to know an image is available.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agent.context import build_context
from app.db import repositories as repo
from app.db.sqlite import connect, init_db


@pytest.fixture
def conn(tmp_path):
    c = connect(str(tmp_path / "ctx.db"))
    init_db(c)
    yield c
    c.close()


def _instruction_present(messages: list) -> bool:
    """Return True if the injected analyze_image instruction is in the list.

    Keys on "尚未分析" which only appears in the injected SystemMessage, not in
    AGENT_SYSTEM_PROMPT (which mentions analyze_image as a tool name but not
    this phrase).
    """
    return any(
        isinstance(m, SystemMessage) and "尚未分析" in m.content
        for m in messages
    )


def test_returns_list_of_base_messages(conn):
    cid = repo.create_conversation(conn)
    repo.add_message(conn, cid, "user", "你好")

    messages = build_context(conn, cid, "你好")

    assert isinstance(messages, list)
    assert len(messages) >= 2  # at least system + 1 history item
    assert isinstance(messages[0], SystemMessage)


def test_history_converted_to_correct_message_types(conn):
    cid = repo.create_conversation(conn)
    repo.add_message(conn, cid, "user", "请识别隐患")
    repo.add_message(conn, cid, "assistant", "发现1处隐患。")
    repo.add_message(conn, cid, "user", "哪个最严重")

    messages = build_context(conn, cid, "哪个最严重")

    # Strip leading SystemMessage(s) to get the history portion.
    history = [m for m in messages if not isinstance(m, SystemMessage)]
    assert len(history) == 3
    assert isinstance(history[0], HumanMessage)
    assert isinstance(history[1], AIMessage)
    assert isinstance(history[2], HumanMessage)
    assert history[0].content == "请识别隐患"
    assert history[1].content == "发现1处隐患。"


def test_new_image_injects_analyze_instruction(conn):
    cid = repo.create_conversation(conn)
    repo.add_uploaded_image(
        conn, cid, "runtime/uploads/x.jpg", "x.jpg", "image/jpeg", 100
    )
    repo.add_message(conn, cid, "user", "请识别隐患")

    messages = build_context(conn, cid, "请识别隐患", new_image_uploaded=True)

    assert _instruction_present(messages)


def test_followup_without_new_image_has_no_instruction(conn):
    cid = repo.create_conversation(conn)
    repo.add_uploaded_image(
        conn, cid, "runtime/uploads/x.jpg", "x.jpg", "image/jpeg", 100
    )
    repo.add_message(conn, cid, "user", "哪个最严重")

    messages = build_context(conn, cid, "哪个最严重", new_image_uploaded=False)

    assert not _instruction_present(messages)


def test_new_image_flag_without_any_image_does_not_inject(conn):
    """Flag set but no image row — must not inject a misleading instruction."""
    cid = repo.create_conversation(conn)
    repo.add_message(conn, cid, "user", "test")

    messages = build_context(conn, cid, "test", new_image_uploaded=True)

    assert not _instruction_present(messages)


def test_preference_memory_injected_as_system_message(conn):
    uid = repo.create_user(conn, "alice", "h")
    repo.upsert_preferences(conn, uid, preference_summary="关注高处作业安全")
    cid = repo.create_conversation(conn, user_id=uid)
    repo.add_message(conn, cid, "user", "你好")

    messages = build_context(conn, cid, "你好", user_id=uid)

    pref_msgs = [
        m for m in messages
        if isinstance(m, SystemMessage) and "关注高处作业安全" in m.content
    ]
    assert len(pref_msgs) == 1


def test_no_preference_injection_when_no_prefs(conn):
    uid = repo.create_user(conn, "bob", "h")
    cid = repo.create_conversation(conn, user_id=uid)
    repo.add_message(conn, cid, "user", "你好")

    messages = build_context(conn, cid, "你好", user_id=uid)

    # Only the main system prompt SystemMessage — no preference SystemMessage.
    system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
    assert len(system_msgs) == 1


def test_no_preference_injection_without_user_id(conn):
    cid = repo.create_conversation(conn)
    repo.add_message(conn, cid, "user", "你好")

    messages = build_context(conn, cid, "你好")

    system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
    assert len(system_msgs) == 1

"""Tests for conversation context assembly (v0.2 / LangGraph).

build_context now returns an AgentContext(system_prompt: str, messages: list[BaseMessage]).
system_prompt is a plain string for create_react_agent's state_modifier parameter.
messages contains only HumanMessage / AIMessage objects — no SystemMessages.
Image-upload and preference instructions are merged into system_prompt so that
no SystemMessage ever appears at a non-leading position in the message list.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agent.context import AgentContext, build_context
from app.db import repositories as repo
from app.db.sqlite import connect, init_db


@pytest.fixture
def conn(tmp_path):
    c = connect(str(tmp_path / "ctx.db"))
    init_db(c)
    yield c
    c.close()


def test_returns_agent_context(conn):
    cid = repo.create_conversation(conn)
    repo.add_message(conn, cid, "user", "你好")

    ctx = build_context(conn, cid, "你好")

    assert isinstance(ctx, AgentContext)
    assert isinstance(ctx.system_prompt, str)
    assert isinstance(ctx.messages, list)
    assert len(ctx.messages) >= 1  # at least the 1 history item
    # No SystemMessages in the messages list — all system content is in system_prompt.
    assert not any(isinstance(m, SystemMessage) for m in ctx.messages)


def test_history_converted_to_correct_message_types(conn):
    cid = repo.create_conversation(conn)
    repo.add_message(conn, cid, "user", "请识别隐患")
    repo.add_message(conn, cid, "assistant", "发现1处隐患。")
    repo.add_message(conn, cid, "user", "哪个最严重")

    ctx = build_context(conn, cid, "哪个最严重")

    history = ctx.messages
    assert len(history) == 3
    assert isinstance(history[0], HumanMessage)
    assert isinstance(history[1], AIMessage)
    assert isinstance(history[2], HumanMessage)
    assert history[0].content == "请识别隐患"
    assert history[1].content == "发现1处隐患。"


def test_new_image_injects_analyze_instruction_into_system_prompt(conn):
    cid = repo.create_conversation(conn)
    repo.add_uploaded_image(
        conn, cid, "runtime/uploads/x.jpg", "x.jpg", "image/jpeg", 100
    )
    repo.add_message(conn, cid, "user", "请识别隐患")

    ctx = build_context(conn, cid, "请识别隐患", new_image_uploaded=True)

    assert "尚未分析" in ctx.system_prompt
    # Instruction must NOT appear as a mid-sequence SystemMessage.
    assert not any(
        isinstance(m, SystemMessage) and "尚未分析" in m.content
        for m in ctx.messages
    )


def test_followup_without_new_image_has_no_instruction(conn):
    cid = repo.create_conversation(conn)
    repo.add_uploaded_image(
        conn, cid, "runtime/uploads/x.jpg", "x.jpg", "image/jpeg", 100
    )
    repo.add_message(conn, cid, "user", "哪个最严重")

    ctx = build_context(conn, cid, "哪个最严重", new_image_uploaded=False)

    assert "尚未分析" not in ctx.system_prompt


def test_new_image_flag_without_any_image_does_not_inject(conn):
    """Flag set but no image row in DB — must not inject a misleading instruction."""
    cid = repo.create_conversation(conn)
    repo.add_message(conn, cid, "user", "test")

    ctx = build_context(conn, cid, "test", new_image_uploaded=True)

    assert "尚未分析" not in ctx.system_prompt


def test_preference_memory_injected_into_system_prompt(conn):
    uid = repo.create_user(conn, "alice", "h")
    repo.upsert_preferences(conn, uid, preference_summary="关注高处作业安全")
    cid = repo.create_conversation(conn, user_id=uid)
    repo.add_message(conn, cid, "user", "你好")

    ctx = build_context(conn, cid, "你好", user_id=uid)

    assert "关注高处作业安全" in ctx.system_prompt
    # Must not appear as a mid-sequence SystemMessage.
    assert not any(
        isinstance(m, SystemMessage) and "关注高处作业安全" in m.content
        for m in ctx.messages
    )


def test_no_preference_injection_when_no_prefs(conn):
    uid = repo.create_user(conn, "bob", "h")
    cid = repo.create_conversation(conn, user_id=uid)
    repo.add_message(conn, cid, "user", "你好")

    ctx = build_context(conn, cid, "你好", user_id=uid)

    # system_prompt must contain the base system prompt but not any preference.
    assert "关注" not in ctx.system_prompt or "高处作业" not in ctx.system_prompt


def test_no_preference_injection_without_user_id(conn):
    cid = repo.create_conversation(conn)
    repo.add_message(conn, cid, "user", "你好")

    ctx = build_context(conn, cid, "你好")

    # Without a user_id, no preference lookup happens.
    assert isinstance(ctx.system_prompt, str)
    assert not any(isinstance(m, SystemMessage) for m in ctx.messages)

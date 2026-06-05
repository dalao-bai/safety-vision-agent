"""Tests for conversation context assembly (U7 / review fix #1).

Verifies that build_context injects an explicit analyze_image instruction when
an image was uploaded this turn — the Agent model only sees text and otherwise
has no way to know an image is available.
"""

from __future__ import annotations

import pytest

from app.agent.context import build_context
from app.db import repositories as repo
from app.db.sqlite import connect, init_db


@pytest.fixture
def conn(tmp_path):
    c = connect(str(tmp_path / "ctx.db"))
    init_db(c)
    yield c
    c.close()


class _StubVLMClient:
    def create(self, *args, **kwargs):  # pragma: no cover - never called here
        raise AssertionError("VLM client should not be called by build_context")


def _instruction_present(input_items) -> bool:
    # Match the distinctive text of the injected instruction. The base
    # AGENT_SYSTEM_PROMPT also mentions "analyze_image" (it lists the tools),
    # so we key on "尚未分析", which only appears in the injected message.
    return any(
        item["role"] == "system" and "尚未分析" in item["content"]
        for item in input_items
    )


def test_new_image_injects_analyze_instruction(conn):
    cid = repo.create_conversation(conn)
    repo.add_uploaded_image(
        conn, cid, "runtime/uploads/x.jpg", "x.jpg", "image/jpeg", 100
    )
    repo.add_message(conn, cid, "user", "请识别隐患")

    loaded = build_context(
        conn, cid, "请识别隐患", _StubVLMClient(), "vlm-model",
        new_image_uploaded=True,
    )

    assert _instruction_present(loaded.input_items)
    # And the tool context can actually run the analysis.
    assert loaded.tool_context.image_path == "runtime/uploads/x.jpg"


def test_followup_without_new_image_has_no_instruction(conn):
    cid = repo.create_conversation(conn)
    repo.add_uploaded_image(
        conn, cid, "runtime/uploads/x.jpg", "x.jpg", "image/jpeg", 100
    )
    repo.add_message(conn, cid, "user", "哪个最严重")

    # Follow-up turn: image exists from before, but none uploaded this turn.
    loaded = build_context(
        conn, cid, "哪个最严重", _StubVLMClient(), "vlm-model",
        new_image_uploaded=False,
    )

    assert not _instruction_present(loaded.input_items)


def test_new_image_flag_without_any_image_does_not_inject(conn):
    # Defensive: flag set but no image row — must not inject a misleading
    # instruction the tool couldn't satisfy.
    cid = repo.create_conversation(conn)
    repo.add_message(conn, cid, "user", "test")

    loaded = build_context(
        conn, cid, "test", _StubVLMClient(), "vlm-model",
        new_image_uploaded=True,
    )

    assert not _instruction_present(loaded.input_items)

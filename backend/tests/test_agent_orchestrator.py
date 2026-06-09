"""Tests for the Agent orchestrator (v0.2 / LangGraph create_react_agent).

Uses a patched create_react_agent that returns a scripted sequence of LangChain
AIMessages — no network access. Verifies that run_turn drives tool calls via
the agent executor, persists audit records, and handles error/cap cases.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from app.agent.orchestrator import run_turn
from app.db import repositories as repo
from app.db.sqlite import connect, init_db
from app.services.responses_client import ResponsesResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def conn(tmp_path):
    c = connect(str(tmp_path / "t.db"))
    init_db(c)
    yield c
    c.close()


_VALID_VLM = json.dumps(
    {
        "summary": "存在隐患",
        "hazards": [
            {
                "name": "未系安全带",
                "location": "顶部",
                "risk_level": "high",
                "basis": "高处无防护",
                "remediation": "佩戴安全带",
                "confidence": 0.9,
            },
            {
                "name": "临边无防护",
                "location": "楼层边缘",
                "risk_level": "critical",
                "basis": "临边缺护栏",
                "remediation": "安装护栏",
                "confidence": 0.95,
            },
        ],
        "needs_followup": False,
        "followup_question": None,
    },
    ensure_ascii=False,
)


class _FakeVLMClient:
    def __init__(self, text=_VALID_VLM):
        self._text = text

    def create(self, model, input_items, tools=None, text_format=None):
        return ResponsesResult(text=self._text, provider_id="resp_vlm", raw=None)


def _fake_settings():
    s = MagicMock()
    s.openai_api_base_url = "https://api.test.local/v1"
    s.openai_api_key = "sk-test"
    s.agent_model = "test-agent"
    return s


def _setup_conversation_with_image(conn, tmp_path):
    img = tmp_path / "x.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0bytes")
    cid = repo.create_conversation(conn)
    repo.add_uploaded_image(conn, cid, str(img), "x.jpg", "image/jpeg", 100)
    return cid


def _make_agent_executor(final_answer: str):
    """Return a mock agent_executor whose .invoke() returns a single AIMessage."""
    executor = MagicMock()
    executor.invoke.return_value = {
        "messages": [AIMessage(content=final_answer)]
    }
    return executor


# ---------------------------------------------------------------------------
# Helpers to patch the LangGraph stack
# ---------------------------------------------------------------------------

def _run(conn, cid, message, final_answer, vlm=None, max_iterations=5,
         new_image_uploaded=False, user_id=None,
         regulation_search=None, report_scheduler=None):
    """Call run_turn with create_react_agent and make_agent_llm patched out."""
    executor = _make_agent_executor(final_answer)
    vlm = vlm or _FakeVLMClient()

    with patch("app.agent.orchestrator.create_react_agent", return_value=executor), \
         patch("app.agent.orchestrator.make_agent_llm", return_value=MagicMock()):
        return run_turn(
            conn, cid, message,
            vlm_client=vlm,
            vlm_model="vlm-model",
            settings=_fake_settings(),
            max_iterations=max_iterations,
            new_image_uploaded=new_image_uploaded,
            user_id=user_id,
            regulation_search=regulation_search,
            report_scheduler=report_scheduler,
        )


# ---------------------------------------------------------------------------
# Core behaviour
# ---------------------------------------------------------------------------

def test_direct_answer_is_saved_and_returned(conn):
    cid = repo.create_conversation(conn)
    repo.add_message(conn, cid, "user", "你好")

    result = _run(conn, cid, "你好", "你好，有什么可以帮你？")

    assert result.answer == "你好，有什么可以帮你？"
    assert result.tool_calls == []
    messages = repo.list_messages(conn, cid)
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["content"] == "你好，有什么可以帮你？"


def test_analysis_returned_when_available(conn, tmp_path):
    cid = _setup_conversation_with_image(conn, tmp_path)
    repo.save_analysis_result(conn, cid, json.loads(_VALID_VLM))
    repo.add_message(conn, cid, "user", "哪个最严重")

    result = _run(conn, cid, "哪个最严重", "最严重的是临边无防护。")

    assert result.answer == "最严重的是临边无防护。"
    assert result.analysis is not None
    assert len(result.analysis.hazards) == 2


def test_no_analysis_returns_none(conn):
    cid = repo.create_conversation(conn)
    repo.add_message(conn, cid, "user", "你好")

    result = _run(conn, cid, "你好", "你好！")

    assert result.analysis is None


def test_assistant_message_persisted(conn):
    cid = repo.create_conversation(conn)
    repo.add_message(conn, cid, "user", "测试")

    _run(conn, cid, "测试", "回答内容。")

    messages = repo.list_messages(conn, cid)
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["content"] == "回答内容。"


# ---------------------------------------------------------------------------
# Recursion / error handling
# ---------------------------------------------------------------------------

def test_graph_recursion_error_returns_controlled_message(conn):
    from langgraph.errors import GraphRecursionError

    cid = repo.create_conversation(conn)
    repo.add_message(conn, cid, "user", "loop")

    executor = MagicMock()
    executor.invoke.side_effect = GraphRecursionError("recursion limit")

    with patch("app.agent.orchestrator.create_react_agent", return_value=executor), \
         patch("app.agent.orchestrator.make_agent_llm", return_value=MagicMock()):
        result = run_turn(
            conn, cid, "loop",
            vlm_client=_FakeVLMClient(),
            vlm_model="vlm",
            settings=_fake_settings(),
            max_iterations=3,
        )

    assert "停止" in result.answer
    responses = repo.list_model_responses(conn, cid)
    assert any(
        r["status"] == "error" and "recursion_limit" in (r["error"] or "")
        for r in responses
    )


def test_agent_api_failure_returns_controlled_error(conn):
    cid = repo.create_conversation(conn)
    repo.add_message(conn, cid, "user", "test")

    executor = MagicMock()
    executor.invoke.side_effect = RuntimeError("api down")

    with patch("app.agent.orchestrator.create_react_agent", return_value=executor), \
         patch("app.agent.orchestrator.make_agent_llm", return_value=MagicMock()):
        result = run_turn(
            conn, cid, "test",
            vlm_client=_FakeVLMClient(),
            vlm_model="vlm",
            settings=_fake_settings(),
        )

    assert "错误" in result.answer
    responses = repo.list_model_responses(conn, cid)
    assert any(
        r["status"] == "error" and "api down" in (r["error"] or "")
        for r in responses
    )


def test_empty_final_content_returns_placeholder(conn):
    cid = repo.create_conversation(conn)
    repo.add_message(conn, cid, "user", "test")

    result = _run(conn, cid, "test", "")

    assert result.answer == "(模型未返回文本)"


# ---------------------------------------------------------------------------
# Settings / LLM wiring
# ---------------------------------------------------------------------------

def test_make_agent_llm_called_with_settings(conn):
    cid = repo.create_conversation(conn)
    repo.add_message(conn, cid, "user", "test")
    settings = _fake_settings()
    executor = _make_agent_executor("ok")

    with patch("app.agent.orchestrator.create_react_agent", return_value=executor) as mock_cra, \
         patch("app.agent.orchestrator.make_agent_llm", return_value=MagicMock()) as mock_llm:
        run_turn(
            conn, cid, "test",
            vlm_client=_FakeVLMClient(),
            vlm_model="vlm",
            settings=settings,
        )
        mock_llm.assert_called_once_with(settings)
        assert mock_cra.called

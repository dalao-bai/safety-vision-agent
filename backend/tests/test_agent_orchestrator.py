"""Tests for the Agent orchestrator tool-calling loop (U7).

Uses a scripted fake Agent client (returns a queue of Responses-shaped dicts)
and a fake VLM client. No network access. Verifies the loop drives tool calls,
feeds results back, persists audit records, and handles error/cap cases.
"""

from __future__ import annotations

import json

import pytest

from app.agent.orchestrator import run_turn
from app.db import repositories as repo
from app.db.sqlite import connect, init_db
from app.services.responses_client import ResponsesResult


@pytest.fixture
def conn(tmp_path):
    c = connect(str(tmp_path / "t.db"))
    init_db(c)
    yield c
    c.close()


class _ScriptedAgentClient:
    """raw_create returns the next queued response dict each call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def raw_create(self, **kwargs):
        self.calls += 1
        if not self._responses:
            raise AssertionError("agent client called more times than scripted")
        return self._responses.pop(0)


class _FakeVLMClient:
    def __init__(self, text):
        self._text = text

    def create(self, model, input_items, tools=None, text_format=None):
        return ResponsesResult(text=self._text, provider_id="resp_vlm", raw=None)


def _fn_call(call_id, name, args=None):
    return {
        "id": f"resp_{call_id}",
        "output": [
            {
                "type": "function_call",
                "call_id": call_id,
                "name": name,
                "arguments": json.dumps(args or {}),
            }
        ],
    }


def _final(text):
    return {"id": "resp_final", "output_text": text, "output": []}


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


def _setup_conversation_with_image(conn):
    cid = repo.create_conversation(conn)
    repo.add_uploaded_image(
        conn, cid, "runtime/uploads/x.jpg", "x.jpg", "image/jpeg", 100
    )
    return cid


def test_initial_image_message_triggers_analyze_and_final_answer(conn, tmp_path):
    # Make the image path real so the analyzer can read it.
    img = tmp_path / "x.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0bytes")
    cid = repo.create_conversation(conn)
    image_id = repo.add_uploaded_image(
        conn, cid, str(img), "x.jpg", "image/jpeg", 100
    )
    repo.add_message(conn, cid, "user", "请识别隐患")

    agent = _ScriptedAgentClient([
        _fn_call("c1", "analyze_image", {}),
        _final("照片中发现2处隐患。"),
    ])
    vlm = _FakeVLMClient(_VALID_VLM)

    result = run_turn(
        conn, cid, "请识别隐患", agent, "agent-model", vlm, "vlm-model"
    )

    assert result.answer == "照片中发现2处隐患。"
    assert any(t.tool_name == "analyze_image" for t in result.tool_calls)
    # Analysis was persisted and linked to the image.
    saved = repo.get_latest_analysis(conn, cid)
    assert saved is not None
    assert len(saved["hazards"]) == 2
    # Raw VLM response was persisted for audit.
    responses = repo.list_model_responses(conn, cid)
    assert any(r["model_role"] == "vlm" for r in responses)
    assert any(r["model_role"] == "agent" for r in responses)


def test_followup_rank_risks(conn):
    cid = _setup_conversation_with_image(conn)
    # Seed a prior analysis.
    repo.save_analysis_result(conn, cid, json.loads(_VALID_VLM))
    repo.add_message(conn, cid, "user", "哪个最严重")

    agent = _ScriptedAgentClient([
        _fn_call("c1", "rank_risks", {}),
        _final("最严重的是临边无防护。"),
    ])
    vlm = _FakeVLMClient(_VALID_VLM)

    result = run_turn(conn, cid, "哪个最严重", agent, "agent-model", vlm, "vlm-model")

    rank_call = next(t for t in result.tool_calls if t.tool_name == "rank_risks")
    assert rank_call.status == "success"
    assert rank_call.output["ranked"][0]["name"] == "临边无防护"
    assert result.answer == "最严重的是临边无防护。"


def test_followup_explain_basis(conn):
    cid = _setup_conversation_with_image(conn)
    repo.save_analysis_result(conn, cid, json.loads(_VALID_VLM))
    repo.add_message(conn, cid, "user", "依据是什么")

    agent = _ScriptedAgentClient([
        _fn_call("c1", "explain_basis", {}),
        _final("依据如下..."),
    ])
    vlm = _FakeVLMClient(_VALID_VLM)

    result = run_turn(conn, cid, "依据是什么", agent, "agent-model", vlm, "vlm-model")
    assert any(t.tool_name == "explain_basis" for t in result.tool_calls)


def test_followup_suggest_remediation(conn):
    cid = _setup_conversation_with_image(conn)
    repo.save_analysis_result(conn, cid, json.loads(_VALID_VLM))
    repo.add_message(conn, cid, "user", "怎么整改")

    agent = _ScriptedAgentClient([
        _fn_call("c1", "suggest_remediation", {}),
        _final("整改建议如下..."),
    ])
    vlm = _FakeVLMClient(_VALID_VLM)

    result = run_turn(conn, cid, "怎么整改", agent, "agent-model", vlm, "vlm-model")
    assert any(t.tool_name == "suggest_remediation" for t in result.tool_calls)


def test_direct_answer_without_tool_call_is_saved(conn):
    cid = repo.create_conversation(conn)
    repo.add_message(conn, cid, "user", "你好")

    agent = _ScriptedAgentClient([_final("你好,有什么可以帮你?")])
    vlm = _FakeVLMClient(_VALID_VLM)

    result = run_turn(conn, cid, "你好", agent, "agent-model", vlm, "vlm-model")
    assert result.answer == "你好,有什么可以帮你?"
    assert result.tool_calls == []
    # Assistant message persisted.
    messages = repo.list_messages(conn, cid)
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["content"] == "你好,有什么可以帮你?"


def test_tool_failure_is_persisted_and_surfaced(conn):
    cid = repo.create_conversation(conn)
    repo.add_message(conn, cid, "user", "分析一下")
    # No image uploaded, but the model (wrongly) calls analyze_image. The tool
    # returns available=False; the loop continues to a final answer.
    agent = _ScriptedAgentClient([
        _fn_call("c1", "analyze_image", {}),
        _final("没有可分析的照片。"),
    ])
    vlm = _FakeVLMClient(_VALID_VLM)

    result = run_turn(conn, cid, "分析一下", agent, "agent-model", vlm, "vlm-model")
    # Tool call recorded.
    calls = repo.list_tool_calls(conn, cid)
    assert len(calls) == 1
    assert calls[0]["tool_name"] == "analyze_image"
    assert result.answer == "没有可分析的照片。"


def test_unknown_tool_recorded_as_error_then_loop_continues(conn):
    cid = repo.create_conversation(conn)
    repo.add_message(conn, cid, "user", "test")
    agent = _ScriptedAgentClient([
        _fn_call("c1", "bogus_tool", {}),
        _final("已处理。"),
    ])
    vlm = _FakeVLMClient(_VALID_VLM)

    result = run_turn(conn, cid, "test", agent, "agent-model", vlm, "vlm-model")
    calls = repo.list_tool_calls(conn, cid)
    assert calls[0]["status"] == "error"
    assert result.answer == "已处理。"


def test_exceeds_max_iterations_records_error(conn):
    cid = _setup_conversation_with_image(conn)
    repo.save_analysis_result(conn, cid, json.loads(_VALID_VLM))
    repo.add_message(conn, cid, "user", "loop")
    # Always return a tool call, never a final answer.
    agent = _ScriptedAgentClient([_fn_call(f"c{i}", "rank_risks", {}) for i in range(10)])
    vlm = _FakeVLMClient(_VALID_VLM)

    result = run_turn(
        conn, cid, "loop", agent, "agent-model", vlm, "vlm-model", max_iterations=3
    )
    assert "停止" in result.answer
    # An error model_response recording the cap was saved.
    responses = repo.list_model_responses(conn, cid)
    assert any(r["status"] == "error" and "max tool iterations" in (r["error"] or "")
               for r in responses)
    assert agent.calls == 3


def test_agent_api_failure_returns_controlled_error(conn):
    cid = repo.create_conversation(conn)
    repo.add_message(conn, cid, "user", "test")

    class _FailingClient:
        def raw_create(self, **kwargs):
            raise RuntimeError("api down")

    vlm = _FakeVLMClient(_VALID_VLM)
    result = run_turn(conn, cid, "test", _FailingClient(), "agent-model", vlm, "vlm-model")

    assert "错误" in result.answer
    responses = repo.list_model_responses(conn, cid)
    assert any(r["status"] == "error" and "api down" in (r["error"] or "")
               for r in responses)

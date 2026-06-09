"""Tests for the chat API contract (v0.2 / LangGraph).

Uses FastAPI TestClient with dependency overrides so the DB is a temporary
SQLite file and the VLM client is a fake. run_turn is patched directly so
tests control the orchestrator output without needing a real LangGraph executor.
No network access.
"""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api import dependencies as deps
from app.api.auth_deps import CurrentUser, get_current_user
from app.db import repositories as repo
from app.db.sqlite import connect, init_db
from app.main import create_app
from app.models.schemas import AnalysisResult, ToolCallSummary
from app.agent.orchestrator import OrchestratorResult
from app.services.responses_client import ResponsesResult


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
            }
        ],
        "needs_followup": False,
        "followup_question": None,
    },
    ensure_ascii=False,
)

_ANALYSIS = AnalysisResult.model_validate(json.loads(_VALID_VLM))


class _FakeVLMClient:
    def create(self, model, input_items, tools=None, text_format=None):
        return ResponsesResult(text=_VALID_VLM, provider_id="resp_vlm", raw=None)


@pytest.fixture
def client(tmp_path):
    """App with overridden DB + VLM client. run_turn is patched per-test."""
    db_path = tmp_path / "api.db"

    app = create_app()

    _seed_conn = connect(str(db_path))
    init_db(_seed_conn)
    user_id = repo.create_user(_seed_conn, "tester", "hash")
    _seed_conn.close()
    test_user = CurrentUser(id=user_id, username="tester")

    def _override_db():
        conn = connect(str(db_path))
        init_db(conn)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[deps.get_db] = _override_db
    app.dependency_overrides[deps.get_vlm_client] = lambda: _FakeVLMClient()
    app.dependency_overrides[get_current_user] = lambda: test_user

    yield TestClient(app), str(db_path)


def _ok_result(answer="ok", analysis=None, tool_calls=None):
    return OrchestratorResult(
        answer=answer,
        analysis=analysis,
        tool_calls=tool_calls or [],
    )


def test_first_request_with_image_returns_analysis(client):
    test_client, db_path = client
    result = _ok_result(
        answer="发现1处隐患。",
        analysis=_ANALYSIS,
        tool_calls=[ToolCallSummary(tool_name="analyze_image", status="success")],
    )
    with patch("app.api.routes.chat.run_turn", return_value=result):
        resp = test_client.post(
            "/api/chat",
            data={"message": "请识别隐患"},
            files={"image": ("site.jpg", b"\xff\xd8\xff\xe0bytes", "image/jpeg")},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["conversation_id"]
    assert body["answer"] == "发现1处隐患。"
    assert body["analysis"] is not None
    assert body["analysis"]["hazards"][0]["name"] == "未系安全带"
    assert any(t["tool_name"] == "analyze_image" for t in body["tool_calls"])


def test_followup_reuses_conversation_and_analysis(client):
    test_client, db_path = client

    # First turn: analyze.
    first_result = _ok_result(answer="发现1处隐患。", analysis=_ANALYSIS)
    with patch("app.api.routes.chat.run_turn", return_value=first_result):
        first = test_client.post(
            "/api/chat",
            data={"message": "请识别隐患"},
            files={"image": ("site.jpg", b"\xff\xd8\xff\xe0bytes", "image/jpeg")},
        )
    cid = first.json()["conversation_id"]

    # Second turn: follow-up, no image.
    second_result = _ok_result(
        answer="最严重的是未系安全带。",
        analysis=_ANALYSIS,
        tool_calls=[ToolCallSummary(tool_name="rank_risks", status="success")],
    )
    with patch("app.api.routes.chat.run_turn", return_value=second_result):
        second = test_client.post(
            "/api/chat",
            data={"message": "哪个最严重", "conversation_id": cid},
        )

    assert second.status_code == 200
    body = second.json()
    assert body["conversation_id"] == cid
    assert body["answer"] == "最严重的是未系安全带。"
    assert body["analysis"] is not None
    assert any(t["tool_name"] == "rank_risks" for t in body["tool_calls"])


def test_missing_message_returns_validation_error(client):
    test_client, _ = client
    resp = test_client.post("/api/chat", data={})
    assert resp.status_code == 422


def test_empty_message_returns_validation_error(client):
    test_client, _ = client
    with patch("app.api.routes.chat.run_turn", return_value=_ok_result()):
        resp = test_client.post("/api/chat", data={"message": "   "})
    assert resp.status_code == 422


def test_unknown_conversation_id_returns_404(client):
    test_client, _ = client
    with patch("app.api.routes.chat.run_turn", return_value=_ok_result()):
        resp = test_client.post(
            "/api/chat",
            data={"message": "hi", "conversation_id": "does-not-exist"},
        )
    assert resp.status_code == 404


def test_unsupported_image_type_returns_422(client):
    test_client, _ = client
    resp = test_client.post(
        "/api/chat",
        data={"message": "请识别隐患"},
        files={"image": ("evil.gif", b"GIF89a", "image/gif")},
    )
    assert resp.status_code == 422


def test_invalid_image_leaves_no_empty_conversation(client):
    test_client, db_path = client
    resp = test_client.post(
        "/api/chat",
        data={"message": "请识别隐患"},
        files={"image": ("evil.gif", b"GIF89a", "image/gif")},
    )
    assert resp.status_code == 422
    conn = connect(db_path)
    init_db(conn)
    try:
        count = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
    finally:
        conn.close()
    assert count == 0


def test_text_only_message_without_image_works(client):
    test_client, _ = client
    result = _ok_result(answer="你好，请上传施工现场照片。")
    with patch("app.api.routes.chat.run_turn", return_value=result):
        resp = test_client.post("/api/chat", data={"message": "你好"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "你好，请上传施工现场照片。"
    assert body["analysis"] is None


def test_run_turn_called_with_settings_not_agent_client(client):
    """Verify the route passes settings (not agent_client) to run_turn."""
    test_client, _ = client
    with patch("app.api.routes.chat.run_turn", return_value=_ok_result()) as mock_rt:
        test_client.post("/api/chat", data={"message": "test"})
        call_kwargs = mock_rt.call_args
        # settings should be present, agent_client should not be a positional arg
        args = call_kwargs[0] if call_kwargs[0] else []
        kwargs = call_kwargs[1] if call_kwargs[1] else {}
        # run_turn(conn, cid, message, vlm_client, vlm_model, settings, ...)
        # positional: [0]=conn [1]=cid [2]=message [3]=vlm_client [4]=vlm_model [5]=settings
        assert len(args) >= 6
        from app.core.config import Settings
        assert isinstance(args[5], Settings)

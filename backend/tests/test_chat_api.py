"""Tests for the chat API contract (U8).

Uses FastAPI TestClient with dependency overrides so the DB is a temporary
SQLite file and the Agent/VLM clients are fakes. No network access.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.api import dependencies as deps
from app.api.auth_deps import CurrentUser, get_current_user
from app.db import repositories as repo
from app.db.sqlite import connect, init_db
from app.main import create_app
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


class _ScriptedAgentClient:
    def __init__(self, responses):
        self._responses = list(responses)

    def raw_create(self, **kwargs):
        return self._responses.pop(0)


class _FakeVLMClient:
    def create(self, model, input_items, tools=None, text_format=None):
        return ResponsesResult(text=_VALID_VLM, provider_id="resp_vlm", raw=None)


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


@pytest.fixture
def client(tmp_path):
    """App with overridden DB + model clients. The agent client is settable
    per-test via the returned holder."""
    db_path = tmp_path / "api.db"

    holder: dict = {"agent": None, "db_path": str(db_path)}

    app = create_app()

    # Seed a fixed user so chat conversations have a valid user_id FK, and
    # override auth so requests are authenticated as that user (v0.2 multi-user).
    _seed_conn = connect(str(db_path))
    init_db(_seed_conn)
    user_id = repo.create_user(_seed_conn, "tester", "hash")
    _seed_conn.close()
    test_user = CurrentUser(id=user_id, username="tester")

    def _override_db():
        # Fresh connection per request (same as production), pointing at the
        # shared temp file. Avoids SQLite's same-thread restriction under
        # TestClient's threadpool while still persisting data across requests.
        conn = connect(str(db_path))
        init_db(conn)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[deps.get_db] = _override_db
    app.dependency_overrides[deps.get_agent_client] = lambda: holder["agent"]
    app.dependency_overrides[deps.get_vlm_client] = lambda: _FakeVLMClient()
    app.dependency_overrides[get_current_user] = lambda: test_user

    test_client = TestClient(app)
    yield test_client, holder


def test_first_request_with_image_returns_analysis(client):
    test_client, holder = client
    holder["agent"] = _ScriptedAgentClient([
        _fn_call("c1", "analyze_image", {}),
        _final("发现1处隐患。"),
    ])

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
    test_client, holder = client
    # First turn: analyze.
    holder["agent"] = _ScriptedAgentClient([
        _fn_call("c1", "analyze_image", {}),
        _final("发现1处隐患。"),
    ])
    first = test_client.post(
        "/api/chat",
        data={"message": "请识别隐患"},
        files={"image": ("site.jpg", b"\xff\xd8\xff\xe0bytes", "image/jpeg")},
    )
    cid = first.json()["conversation_id"]

    # Second turn: follow-up, no image.
    holder["agent"] = _ScriptedAgentClient([
        _fn_call("c2", "rank_risks", {}),
        _final("最严重的是未系安全带。"),
    ])
    second = test_client.post(
        "/api/chat",
        data={"message": "哪个最严重", "conversation_id": cid},
    )

    assert second.status_code == 200
    body = second.json()
    assert body["conversation_id"] == cid
    assert body["answer"] == "最严重的是未系安全带。"
    # Reused saved analysis without re-uploading.
    assert body["analysis"] is not None
    assert any(t["tool_name"] == "rank_risks" for t in body["tool_calls"])


def test_missing_message_returns_validation_error(client):
    test_client, _ = client
    resp = test_client.post("/api/chat", data={})
    assert resp.status_code == 422


def test_empty_message_returns_validation_error(client):
    test_client, holder = client
    holder["agent"] = _ScriptedAgentClient([_final("x")])
    resp = test_client.post("/api/chat", data={"message": "   "})
    assert resp.status_code == 422


def test_unknown_conversation_id_returns_404(client):
    test_client, holder = client
    holder["agent"] = _ScriptedAgentClient([_final("x")])
    resp = test_client.post(
        "/api/chat",
        data={"message": "hi", "conversation_id": "does-not-exist"},
    )
    assert resp.status_code == 404


def test_unsupported_image_type_returns_422(client):
    test_client, holder = client
    holder["agent"] = _ScriptedAgentClient([_final("x")])
    resp = test_client.post(
        "/api/chat",
        data={"message": "请识别隐患"},
        files={"image": ("evil.gif", b"GIF89a", "image/gif")},
    )
    assert resp.status_code == 422


def test_invalid_image_leaves_no_empty_conversation(client):
    test_client, holder = client
    holder["agent"] = _ScriptedAgentClient([_final("x")])
    resp = test_client.post(
        "/api/chat",
        data={"message": "请识别隐患"},
        files={"image": ("evil.gif", b"GIF89a", "image/gif")},
    )
    assert resp.status_code == 422
    # The rejected request must not have created a conversation.
    conn = connect(holder["db_path"])
    init_db(conn)
    try:
        count = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
    finally:
        conn.close()
    assert count == 0


def test_text_only_message_without_image_works(client):
    test_client, holder = client
    holder["agent"] = _ScriptedAgentClient([_final("你好,请上传施工现场照片。")])
    resp = test_client.post("/api/chat", data={"message": "你好"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "你好,请上传施工现场照片。"
    assert body["analysis"] is None

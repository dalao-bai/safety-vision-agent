from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, kg_path, tiny_png, monkeypatch):
    monkeypatch.setenv("OPENAI_API_BASE_URL", "http://x/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("AGENT_MODEL", "agent-x")
    monkeypatch.setenv("VLM_MODEL", "vlm-x")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "agent.db"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("PIPELINE_INTAKE_DIR", str(tmp_path / "intake"))

    import importlib
    import app.config as config
    importlib.reload(config)

    # deps caches singletons via lru_cache against the OLD settings; reload it too
    import app.api.deps as deps
    importlib.reload(deps)

    # Reload route modules so their Depends() capture the freshly-reloaded deps functions.
    import app.api.sessions as _sessions_mod
    import app.api.images as _images_mod
    import app.api.messages as _messages_mod
    import app.api.reports as _reports_mod
    importlib.reload(_sessions_mod)
    importlib.reload(_images_mod)
    importlib.reload(_messages_mod)
    importlib.reload(_reports_mod)

    import app.main as _main_mod
    importlib.reload(_main_mod)

    from app.main import create_app
    from app.vlm.detector import DetectionResult, Hazard

    app = create_app()

    def fake_detector():
        class _D:
            def detect(self, path):
                return DetectionResult(scene="four_openings_edges", hazards=[
                    Hazard(object_id="foundation_pit_edge_protection", object_name="基坑临边防护",
                           status="confirmed_hazard", hazard_type_id="missing_protection", hazard_type="防护缺失",
                           bbox=[0, 278, 999, 999], visual_evidence="未见连续防护栏杆", rule_basis="rb",
                           evidence_sufficiency="sufficient", uncertainty_reason=None, reasoning_chain=[],
                           missing_evidence=None)])
        return _D()
    app.dependency_overrides[deps.get_detector] = fake_detector

    def fake_agent_client():
        def create(**kwargs):
            msg = SimpleNamespace(content="收到,已确认。", tool_calls=None)
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    app.dependency_overrides[deps.get_agent_client] = fake_agent_client

    def fake_standards():
        return SimpleNamespace(search=lambda q, top_k=3: [{"text": "t", "source": "s.md", "heading": "h"}])
    app.dependency_overrides[deps.get_standards] = fake_standards

    return TestClient(app), tiny_png


def test_full_flow(client):
    c, tiny_png = client
    sid = c.post("/sessions").json()["session_id"]

    with open(tiny_png, "rb") as f:
        r = c.post(f"/sessions/{sid}/images", files={"file": ("site.png", f, "image/png")})
    assert r.status_code == 200
    body = r.json()
    assert body["image_id"] >= 1
    assert "是否正确" in body["assistant_message"]
    assert len(body["hazards"]) == 1

    r2 = c.post(f"/sessions/{sid}/messages", json={"text": "对的,没问题"})
    assert r2.status_code == 200
    assert "确认" in r2.json()["reply"]

    r3 = c.post(f"/sessions/{sid}/report")
    assert r3.status_code == 200
    assert r3.json()["report_path"].endswith(".md")


def test_unknown_session_404(client):
    c, _ = client
    assert c.post("/sessions/9999/messages", json={"text": "x"}).status_code == 404


def test_reject_bad_image_type(client):
    c, _ = client
    sid = c.post("/sessions").json()["session_id"]
    r = c.post(f"/sessions/{sid}/images", files={"file": ("x.txt", b"hello", "text/plain")})
    assert r.status_code == 400

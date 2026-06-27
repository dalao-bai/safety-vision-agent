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

    import app.config as config
    import app.api.deps as deps
    # clear cached settings + singletons so this test binds to the temp paths above
    config.get_settings.cache_clear()
    for fn in (deps.get_db, deps.get_kg, deps.get_standards, deps.get_intake,
               deps.get_agent_client, deps.get_detector):
        fn.cache_clear()

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


def test_unknown_session_404(client):
    c, _ = client
    assert c.post("/sessions/9999/messages", json={"text": "x"}).status_code == 404


def test_reject_bad_image_type(client):
    c, _ = client
    sid = c.post("/sessions").json()["session_id"]
    r = c.post(f"/sessions/{sid}/images", files={"file": ("x.txt", b"hello", "text/plain")})
    assert r.status_code == 400


def test_batch_upload_success(client):
    c, tiny_png = client
    sid = c.post("/sessions").json()["session_id"]
    png_bytes = tiny_png.read_bytes()

    r = c.post(f"/sessions/{sid}/images/batch", files=[
        ("files", ("a.png", png_bytes, "image/png")),
        ("files", ("b.png", png_bytes, "image/png")),
    ])
    assert r.status_code == 200
    body = r.json()
    assert body["succeeded"] == 2
    assert body["failed"] == 0
    assert body["total"] == 2
    assert "batch_id" in body
    assert "已完成 2 张图识别" in body["assistant_message"]


def test_batch_upload_invalid_type_skipped(client):
    c, tiny_png = client
    sid = c.post("/sessions").json()["session_id"]

    r = c.post(f"/sessions/{sid}/images/batch", files=[
        ("files", ("a.png", tiny_png.read_bytes(), "image/png")),
        ("files", ("b.pdf", b"not-a-pdf", "application/pdf")),
    ])
    assert r.status_code == 200
    body = r.json()
    assert body["succeeded"] == 1
    assert body["failed"] == 1
    assert body["failed_files"][0]["reason"] == "unsupported_type"


def test_batch_upload_all_invalid_returns_422(client):
    c, _ = client
    sid = c.post("/sessions").json()["session_id"]
    r = c.post(f"/sessions/{sid}/images/batch", files=[
        ("files", ("a.pdf", b"x", "application/pdf")),
    ])
    assert r.status_code == 422


def test_batch_upload_unknown_session_404(client):
    c, tiny_png = client
    r = c.post("/sessions/9999/images/batch", files=[
        ("files", ("a.png", tiny_png.read_bytes(), "image/png")),
    ])
    assert r.status_code == 404


def test_reject_oversize_image(tmp_path, kg_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setenv("OPENAI_API_BASE_URL", "http://x/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("AGENT_MODEL", "agent-x")
    monkeypatch.setenv("VLM_MODEL", "vlm-x")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "agent.db"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("MAX_IMAGE_BYTES", "10")
    import app.config as config
    import app.api.deps as deps
    config.get_settings.cache_clear()
    for fn in (deps.get_db, deps.get_kg, deps.get_standards, deps.get_intake,
               deps.get_agent_client, deps.get_detector):
        fn.cache_clear()
    from app.main import create_app
    from fastapi.testclient import TestClient
    app = create_app()
    # override all external deps so no real model or openai client is needed
    from app.vlm.detector import DetectionResult
    app.dependency_overrides[deps.get_detector] = lambda: type("D", (), {"detect": lambda self, p: DetectionResult(scene="s", hazards=[])})()
    app.dependency_overrides[deps.get_agent_client] = lambda: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=None))])))
    )
    app.dependency_overrides[deps.get_standards] = lambda: SimpleNamespace(
        search=lambda q, top_k=3: []
    )
    c = TestClient(app)
    sid = c.post("/sessions").json()["session_id"]
    r = c.post(f"/sessions/{sid}/images", files={"file": ("big.png", b"x" * 50, "image/png")})
    assert r.status_code == 413

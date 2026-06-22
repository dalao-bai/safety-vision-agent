import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tests.conftest import _tiny_png_bytes


@pytest.fixture
def app_client(tmp_path, kg_path, monkeypatch):
    for k, v in {
        "OPENAI_API_BASE_URL": "http://x/v1", "OPENAI_API_KEY": "k",
        "AGENT_MODEL": "agent-x", "VLM_MODEL": "vlm-x",
        "DATABASE_PATH": str(tmp_path / "agent.db"), "UPLOAD_DIR": str(tmp_path / "uploads"),
        "REPORT_DIR": str(tmp_path / "reports"), "PIPELINE_INTAKE_DIR": str(tmp_path / "intake"),
    }.items():
        monkeypatch.setenv(k, v)

    import app.config as config
    import app.api.deps as deps
    import app.api.images as _images_mod
    import app.api.messages as _messages_mod
    # Clear the lru_cache on EVERY known reference to get_settings.
    # importlib.reload(config) in test_config.py creates a new get_settings object;
    # route modules (images, messages) keep the OLD reference via their module-level
    # `from app.config import get_settings` binding.  We must clear all of them.
    seen = set()
    for ref in (config.get_settings, _images_mod.get_settings, _messages_mod.get_settings):
        if id(ref) not in seen:
            ref.cache_clear()
            seen.add(id(ref))
    for fn in (deps.get_db, deps.get_kg, deps.get_standards, deps.get_intake,
               deps.get_agent_client, deps.get_detector):
        fn.cache_clear()

    from app.main import create_app
    from app.vlm.detector import DetectionResult, Hazard

    app = create_app()

    # real detector replaced with a stub returning the user's flagship hazard
    app.dependency_overrides[deps.get_detector] = lambda: SimpleNamespace(detect=lambda p: DetectionResult(
        scene="four_openings_edges", hazards=[Hazard(
            object_id="foundation_pit_edge_protection", object_name="基坑临边防护",
            status="confirmed_hazard", hazard_type_id="missing_protection", hazard_type="防护缺失",
            bbox=[0, 278, 999, 999], visual_evidence="未见连续防护栏杆", rule_basis="rb",
            evidence_sufficiency="sufficient", uncertainty_reason=None, reasoning_chain=[],
            missing_evidence=None)]))

    # scripted agent: 1st turn calls submit_correction(image_id=1), 2nd turn answers
    state = {"n": 0}
    def create(**kwargs):
        state["n"] += 1
        if state["n"] == 1:
            tc = SimpleNamespace(id="c0", type="function",
                function=SimpleNamespace(name="submit_correction",
                    arguments=json.dumps({"image_id": 1, "note": "基坑框偏大"})))
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="", tool_calls=[tc]))])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content="已记录纠错并送入标注流水线。", tool_calls=None))])
    app.dependency_overrides[deps.get_agent_client] = lambda: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    # standards stub to avoid network embeddings
    app.dependency_overrides[deps.get_standards] = lambda: SimpleNamespace(
        search=lambda q, top_k=3: [{"text": "基坑周边设置防护栏杆", "source": "JGJ59.md", "heading": "B.13"}])
    return TestClient(app), tmp_path


def _png(tmp_path: Path) -> Path:
    p = tmp_path / "site.png"
    p.write_bytes(_tiny_png_bytes())
    return p


def test_correction_pipeline_intake_endtoend(app_client):
    c, tmp_path = app_client
    sid = c.post("/sessions").json()["session_id"]
    with open(_png(tmp_path), "rb") as f:
        r = c.post(f"/sessions/{sid}/images", files={"file": ("site.png", f, "image/png")})
    assert r.status_code == 200
    assert r.json()["image_id"] == 1

    reply = c.post(f"/sessions/{sid}/messages", json={"text": "不对,基坑框偏大"}).json()["reply"]
    assert "流水线" in reply

    intake = tmp_path / "intake"
    paired = list((intake / "images").glob("*.json"))
    assert len(paired) == 1
    doc = json.loads(paired[0].read_text(encoding="utf-8"))
    assert doc["agent_correction_note"] == "基坑框偏大"
    assert doc["objects"][0]["object_id"] == "foundation_pit_edge_protection"
    assert list((intake / "corrections").glob("*.correction.json"))


def test_qa_flow_endtoend(app_client):
    """Upload, confirm correct, then a normal Q&A turn returns a string reply."""
    c, tmp_path = app_client
    sid = c.post("/sessions").json()["session_id"]
    with open(_png(tmp_path), "rb") as f:
        c.post(f"/sessions/{sid}/images", files={"file": ("site.png", f, "image/png")})
    # second message turn -> scripted agent's state["n"] increments; first turn here is n=1
    # (this test does not assert correction; it just confirms the message endpoint returns 200 + string)
    r = c.post(f"/sessions/{sid}/messages", json={"text": "这个隐患依据是什么?"})
    assert r.status_code == 200
    assert isinstance(r.json()["reply"], str)

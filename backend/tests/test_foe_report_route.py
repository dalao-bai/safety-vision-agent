# backend/tests/test_foe_report_route.py
import pytest
from fastapi.testclient import TestClient

from app.api.auth_deps import CurrentUser, get_current_user
from app.main import app
from app.models.foe_schemas import ClauseRef


class _FakeRetriever:
    def retrieve(self, obj):
        return [ClauseRef(standard_code="JGJ 80-2016", clause_id="第4.1.1条",
                          official_text="应设置防护栏杆。", source_raw="x")]


@pytest.fixture
def client(monkeypatch):
    # 覆盖认证
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="u1", username="t")
    # 用假检索器，避免读真实标准全文
    import app.api.routes.foe_report as route
    monkeypatch.setattr(route, "get_clause_retriever", lambda: _FakeRetriever())
    yield TestClient(app)
    app.dependency_overrides.clear()


_BODY = {
    "title": "测试",
    "analyses": [{
        "objects": [{
            "related_object": "基坑临边防护", "object_bbox": [0, 0, 1, 1],
            "status": "confirmed_hazard", "hazard_type_id": "missing_protection",
            "hazard_type": "防护缺失", "visual_evidence": "x",
        }]
    }],
}


def test_generate_then_status_then_download(client):
    resp = client.post("/api/foe/report", json=_BODY)
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]

    status = client.get(f"/api/foe/report/status/{task_id}")
    assert status.status_code == 200
    assert status.json()["status"] == "done"  # BackgroundTasks 在测试请求内已执行

    dl = client.get(f"/api/foe/report/download/{task_id}")
    assert dl.status_code == 200
    assert "wordprocessingml" in dl.headers["content-type"]


def test_status_foreign_task_404(client):
    resp = client.post("/api/foe/report", json=_BODY)
    task_id = resp.json()["task_id"]
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="other", username="o")
    assert client.get(f"/api/foe/report/status/{task_id}").status_code == 404

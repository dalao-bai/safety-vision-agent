import pytest

from app.core.config import get_settings
from app.db import repositories
from app.db.sqlite import initialize_database
from app.models.schemas import HazardObject
from app.services.memory import hazard_by_index


@pytest.fixture()
def sqlite_db(tmp_path, monkeypatch):
    monkeypatch.setenv("SQLITE_PATH", (tmp_path / "agent.sqlite3").as_posix())
    get_settings.cache_clear()
    initialize_database()
    return tmp_path


def test_memory_resolves_second_hazard_from_latest_result(sqlite_db) -> None:
    conversation = repositories.get_or_create_conversation(None)
    analysis = repositories.create_analysis_task(conversation.id, "/tmp/site.jpg", "分析")
    hazards = [
        HazardObject(object_id="edge", object_name="临边", bbox=[0, 0, 1, 1], status="confirmed_hazard", visual_evidence="无防护", rule="规则 1"),
        HazardObject(object_id="opening", object_name="洞口", bbox=[1, 1, 2, 2], status="confirmed_hazard", visual_evidence="未覆盖", rule="规则 2"),
    ]
    repositories.save_analysis_results(
        analysis.id,
        {"objects": [item.model_dump() for item in hazards], "summary": "vlm"},
        {"detections": [], "summary": {}},
        {"hazards": [item.model_dump() for item in hazards], "detections": [], "uncertain_items": [], "summary": "2 个隐患", "recommendations": []},
    )

    context = hazard_by_index(conversation.id, "刚才第 2 个隐患依据是什么？")

    assert context["index"] == 1
    assert context["hazard"]["object_name"] == "洞口"

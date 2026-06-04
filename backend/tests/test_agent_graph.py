import pytest

from app.agent.graph import run_safety_agent
from app.core.config import get_settings
from app.db import repositories
from app.db.sqlite import initialize_database
from app.models.schemas import HazardObject


@pytest.fixture()
def graph_db(tmp_path, monkeypatch):
    monkeypatch.setenv("SQLITE_PATH", (tmp_path / "agent.sqlite3").as_posix())
    monkeypatch.setenv("UPLOAD_DIR", tmp_path.as_posix())
    get_settings.cache_clear()
    image = tmp_path / "site.jpg"
    image.write_bytes(b"fake image")
    initialize_database()
    return image


@pytest.mark.anyio
async def test_graph_reuses_memory_for_follow_up_without_visual_tools(graph_db) -> None:
    first = await run_safety_agent({"user_message": "分析这张图", "image_path": graph_db.as_posix()})

    second = await run_safety_agent({"conversation_id": first["conversation_id"], "user_message": "刚才第 1 个隐患依据是什么？"})

    assert second["conversation_id"] == first["conversation_id"]
    assert second["intent"] == "rule_basis"
    assert all(call["tool"] != "vlm_hazard_analysis_tool" for call in second["tool_calls"])


@pytest.mark.anyio
async def test_graph_requires_image_when_no_memory() -> None:
    result = await run_safety_agent({"user_message": "分析这张图"})

    assert result["intent"] == "need_image"
    assert "上传" in result["answer"]


@pytest.mark.anyio
async def test_react_trace_is_persisted_and_visible(graph_db) -> None:
    result = await run_safety_agent({"user_message": "分析这张图", "image_path": graph_db.as_posix()})

    react_calls = [call for call in result["tool_calls"] if call["tool"].startswith("react_")]
    assert react_calls
    assert react_calls[0]["input"]["step_index"] >= 1
    assert "planner_summary" in react_calls[0]["input"]
    assert "observation" in react_calls[0]


@pytest.mark.anyio
async def test_remediation_advice_does_not_create_task_without_explicit_create(graph_db) -> None:
    first = await run_safety_agent({"user_message": "分析这张图", "image_path": graph_db.as_posix()})

    second = await run_safety_agent({"conversation_id": first["conversation_id"], "user_message": "怎么整改？"})

    assert "remediation_task" not in second["artifacts"]
    assert repositories.list_remediation_tasks(conversation_id=first["conversation_id"]) == []


@pytest.mark.anyio
async def test_risk_score_sorts_seeded_hazards(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SQLITE_PATH", (tmp_path / "agent.sqlite3").as_posix())
    monkeypatch.setenv("UPLOAD_DIR", tmp_path.as_posix())
    get_settings.cache_clear()
    initialize_database()
    conversation = repositories.get_or_create_conversation(None)
    analysis = repositories.create_analysis_task(conversation.id, (tmp_path / "site.jpg").as_posix(), "seed")
    hazards = [
        HazardObject(
            object_id="minor",
            object_name="材料堆放",
            bbox=[0, 0, 1, 1],
            status="confirmed_hazard",
            hazard_type="一般隐患",
            visual_evidence="材料堆放杂乱",
            rule="现场文明施工要求",
            confidence=0.6,
            source_label="图片 1",
        ),
        HazardObject(
            object_id="edge",
            object_name="临边",
            bbox=[0, 0, 1, 1],
            status="confirmed_hazard",
            hazard_type="临边防护缺失",
            visual_evidence="人员靠近临边，未见连续防护栏杆",
            rule="临边作业应设置防护",
            confidence=0.9,
            source_label="图片 2",
        ),
    ]
    repositories.save_analysis_results(
        analysis.id,
        {"objects": [item.model_dump() for item in hazards], "summary": "seed"},
        {"detections": [], "summary": {}},
        {"hazards": [item.model_dump() for item in hazards], "detections": [], "uncertain_items": [], "summary": "2 个隐患", "recommendations": []},
    )

    result = await run_safety_agent({"conversation_id": conversation.id, "user_message": "哪个最严重？"})
    fused = result["latest_fused_result"]
    follow_up = await run_safety_agent({"conversation_id": conversation.id, "user_message": "为什么第 1 个风险最高？"})

    assert fused["hazards"][0]["object_name"] == "临边"
    assert fused["hazards"][0]["risk_level"] in {"high", "critical"}
    assert "图片 2" in result["answer"]
    assert follow_up["selected_hazard"]["object_name"] == "临边"

import pytest

from app.agent.graph import run_safety_agent
from app.agent import tools
from app.core.config import get_settings
from app.db import repositories
from app.db.sqlite import initialize_database
from app.models.schemas import HazardObject
from app.models.schemas import FusedResult


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
async def test_single_image_latest_analysis_keeps_real_image_path(graph_db) -> None:
    result = await run_safety_agent({"user_message": "分析这张图", "image_path": graph_db.as_posix()})

    analysis = repositories.get_analysis_task(result["latest_analysis_id"])

    assert analysis.image_path == graph_db.as_posix()


@pytest.mark.anyio
async def test_remediation_advice_does_not_create_task_without_explicit_create(graph_db) -> None:
    first = await run_safety_agent({"user_message": "分析这张图", "image_path": graph_db.as_posix()})

    second = await run_safety_agent({"conversation_id": first["conversation_id"], "user_message": "怎么整改？"})

    assert "remediation_task" not in second["artifacts"]
    assert repositories.list_remediation_tasks(conversation_id=first["conversation_id"]) == []


@pytest.mark.anyio
async def test_visual_tool_failure_is_reported(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SQLITE_PATH", (tmp_path / "agent.sqlite3").as_posix())
    monkeypatch.setenv("UPLOAD_DIR", tmp_path.as_posix())
    monkeypatch.setenv("VLM_API_BASE_URL", "http://127.0.0.1:1/unavailable")
    monkeypatch.setenv("VLM_API_KEY", "")
    monkeypatch.setenv("VLM_MODEL_NAME", "test")
    get_settings.cache_clear()
    image = tmp_path / "site.jpg"
    image.write_bytes(b"fake image")
    initialize_database()

    result = await run_safety_agent({"user_message": "分析这张图", "image_path": image.as_posix()})

    assert result["errors"][0]["code"] == "visual_tool_failed"
    assert "失败" in result["answer"]


@pytest.mark.anyio
async def test_multi_image_partial_failure_keeps_successful_result(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SQLITE_PATH", (tmp_path / "agent.sqlite3").as_posix())
    monkeypatch.setenv("UPLOAD_DIR", tmp_path.as_posix())
    get_settings.cache_clear()
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    first.write_bytes(b"fake image")
    second.write_bytes(b"fake image")
    initialize_database()

    async def fake_analysis(conversation_id, message, file_id, image_path, selected_bbox):
        if image_path == first.as_posix():
            hazard = HazardObject(
                object_id="edge",
                object_name="临边",
                bbox=[0, 0, 1, 1],
                status="confirmed_hazard",
                hazard_type="临边防护缺失",
                visual_evidence="临边未见防护",
                rule="临边应设置防护",
            )
            analysis = repositories.create_analysis_task(conversation_id, image_path, message)
            fused = FusedResult(hazards=[hazard], summary="1 个隐患")
            repositories.save_fused_result(analysis.id, fused.model_dump())
            return {"analysis_id": analysis.id, "image_path": image_path, "fused_result": fused, "tool_calls": []}
        analysis = repositories.create_analysis_task(conversation_id, image_path, message, status="failed")
        return {"analysis_id": analysis.id, "image_path": image_path, "fused_result": None, "tool_calls": [], "error": "visual_tool_failed"}

    monkeypatch.setattr(tools, "run_image_analysis_tool", fake_analysis)

    result = await run_safety_agent({"user_message": "比较两张图", "image_paths": [first.as_posix(), second.as_posix()]})

    assert result["latest_fused_result"]["hazards"][0]["source_label"] == "图片 1"
    assert result["errors"][0]["code"] == "visual_tool_failed"
    assert result["artifacts"]["analyses"][1]["error"] == "visual_tool_failed"


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

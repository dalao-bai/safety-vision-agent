import pytest

from app.agent.graph import run_safety_agent
from app.core.config import get_settings
from app.db.sqlite import initialize_database


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

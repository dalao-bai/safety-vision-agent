import pytest

from app.api.routes.chat import chat
from app.core.config import get_settings
from app.db.sqlite import initialize_database
from app.models.schemas import AgentChatRequest


@pytest.mark.anyio
async def test_chat_with_image_path_returns_agent_response(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SQLITE_PATH", (tmp_path / "agent.sqlite3").as_posix())
    monkeypatch.setenv("UPLOAD_DIR", tmp_path.as_posix())
    get_settings.cache_clear()
    initialize_database()
    image = tmp_path / "site.jpg"
    image.write_bytes(b"fake")

    response = await chat(AgentChatRequest(message="分析这张图", image_path=image.as_posix()))

    assert response.conversation_id.startswith("conv_")
    assert response.latest_analysis_id.startswith("analysis_")
    assert response.fused_result is not None
    assert response.fused_result.summary


@pytest.mark.anyio
async def test_chat_followup_uses_same_conversation(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SQLITE_PATH", (tmp_path / "agent.sqlite3").as_posix())
    monkeypatch.setenv("UPLOAD_DIR", tmp_path.as_posix())
    get_settings.cache_clear()
    initialize_database()
    image = tmp_path / "site.jpg"
    image.write_bytes(b"fake")

    first = await chat(AgentChatRequest(message="分析这张图", image_path=image.as_posix()))
    second = await chat(AgentChatRequest(conversation_id=first.conversation_id, message="刚才第 1 个隐患依据是什么？"))

    assert second.conversation_id == first.conversation_id
    assert all(call["tool"] != "vlm_hazard_analysis_tool" for call in second.tool_calls)

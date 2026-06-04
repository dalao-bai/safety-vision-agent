from app.core.config import get_settings
from app.db import repositories
from app.db.sqlite import initialize_database


def test_repository_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SQLITE_PATH", (tmp_path / "agent.sqlite3").as_posix())
    get_settings.cache_clear()
    initialize_database()

    conversation = repositories.get_or_create_conversation(None)
    message = repositories.add_message(conversation.id, "user", "分析这张图")
    uploaded = repositories.add_uploaded_file("site.jpg", (tmp_path / "site.jpg").as_posix(), "image/jpeg", conversation.id)
    analysis = repositories.create_analysis_task(conversation.id, uploaded.stored_path, message.content)
    repositories.create_tool_call(conversation.id, analysis.id, "rule_retrieval_tool", "ok", {"q": "rules"}, {"count": 1}, 12.5)
    repositories.save_analysis_results(
        analysis.id,
        {"objects": [], "summary": "vlm"},
        {"detections": [], "summary": {}},
        {"hazards": [], "detections": [], "uncertain_items": [], "summary": "done", "recommendations": []},
    )
    remediation = repositories.create_remediation_task(conversation.id, analysis.id, 0, "整改", "补齐防护", None, None, {})
    batch = repositories.create_annotation_batch("analysis_review")
    sample = repositories.create_annotation_sample(
        batch.id,
        analysis.id,
        conversation.id,
        uploaded.stored_path,
        "analysis_review",
        {},
        {},
        {"summary": "done"},
        {"objects": []},
        {"objects": []},
        "",
    )

    latest = repositories.latest_fused_result(analysis.id)
    calls = repositories.list_tool_calls(conversation.id, analysis.id)

    assert conversation.id.startswith("conv_")
    assert remediation.id.startswith("remed_")
    assert sample.id.startswith("annsample_")
    assert latest.result_json["summary"] == "done"
    assert calls[0].tool_name == "rule_retrieval_tool"

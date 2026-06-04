import pytest
from fastapi import HTTPException

from app.api.routes.annotations import create_from_analysis
from app.core.config import get_settings
from app.db import repositories
from app.db.sqlite import initialize_database
from app.models.schemas import AnnotationFromAnalysisRequest
from app.services.annotation_adapter import build_accepted_records, build_draft_from_analysis


def test_build_accepted_records_from_revised_review() -> None:
    fused_result = {
        "hazards": [
            {
                "object_id": "floor_edge_protection",
                "object_name": "楼层临边防护",
                "bbox": [1, 2, 30, 40],
                "status": "confirmed_hazard",
                "hazard_type_id": "missing_protection",
                "hazard_type": "防护缺失",
                "visual_evidence": "临边未见防护栏杆。",
                "evidence_sufficiency": "sufficient",
                "rule": "楼层临边应设置防护栏杆。",
            }
        ],
        "uncertain_items": [],
    }
    draft = build_draft_from_analysis("sample_1", "uploads/a.jpg", fused_result, {}, {})
    revised = {**draft["objects"][0], "visual_evidence": "人工修正：临边未见连续防护栏杆。"}
    review = {
        "sample_id": "sample_1",
        "image_decision": "accept",
        "source_analysis_id": "analysis_1",
        "objects": [
            {
                "draft_object_index": 1,
                "decision": "revise",
                "revised": revised,
            }
        ],
    }

    records = build_accepted_records("sample_1", "uploads/a.jpg", review, draft)

    assert records["errors"] == []
    assert len(records["images"]) == 1
    assert len(records["objects"]) == 1
    assert records["objects"][0]["gt_bbox"] == [1, 2, 30, 40]
    assert records["objects"][0]["visual_evidence"].startswith("人工修正")


def test_aggregate_analysis_cannot_create_annotation_sample(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SQLITE_PATH", (tmp_path / "agent.sqlite3").as_posix())
    get_settings.cache_clear()
    initialize_database()
    conversation = repositories.get_or_create_conversation(None)
    analysis = repositories.create_analysis_task(conversation.id, "aggregate:multi-image", "比较多图")
    repositories.save_fused_result(
        analysis.id,
        {"hazards": [], "detections": [], "uncertain_items": [], "summary": "aggregate", "recommendations": []},
    )

    with pytest.raises(HTTPException) as exc_info:
        create_from_analysis(AnnotationFromAnalysisRequest(analysis_id=analysis.id))

    assert exc_info.value.status_code == 400

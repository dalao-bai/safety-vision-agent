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

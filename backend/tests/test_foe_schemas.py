# backend/tests/test_foe_schemas.py
import pytest
from pydantic import ValidationError

from app.models.foe_schemas import ClauseRef, FoeAnalysis, FoeObject, FoeReportRequest, ReasoningStep

EXAMPLE_OBJECT = {
    "scene": "四口五临边",
    "reasoning_chain": [
        {"step": "observe", "content": "图中可见基坑开挖形成较深临边…"},
        {"step": "locate", "content": "定位到基坑临边防护…"},
        {"step": "match_rule", "content": "对照候选隐患条款…据此可判定为防护缺失。"},
        {"step": "assess", "content": "证据充分，可下确定判断。"},
    ],
    "related_object": "基坑临边防护",
    "object_bbox": [0, 278, 999, 999],
    "visual_evidence": "图中可见基坑开挖形成较深临边…",
    "rule_basis": "开挖深度2m及以上…未设置防护栏杆…",
    "evidence_sufficiency": "sufficient",
    "uncertainty_reason": None,
    "hazard_type_id": "missing_protection",
    "hazard_type": "防护缺失",
    "status": "confirmed_hazard",
}


def test_foe_object_parses_example():
    obj = FoeObject.model_validate(EXAMPLE_OBJECT)
    assert obj.related_object == "基坑临边防护"
    assert obj.object_bbox == [0, 278, 999, 999]
    assert obj.status == "confirmed_hazard"
    assert obj.hazard_type_id == "missing_protection"
    assert len(obj.reasoning_chain) == 4
    assert obj.reasoning_chain[0].step == "observe"


def test_foe_analysis_wraps_object_list():
    analysis = FoeAnalysis.model_validate(
        {"image_ref": "/tmp/x.png", "objects": [EXAMPLE_OBJECT, EXAMPLE_OBJECT]}
    )
    assert len(analysis.objects) == 2
    assert isinstance(analysis.objects[0], FoeObject)


def test_foe_object_ignores_extra_scene_field():
    # 顶层 example 带 scene，FoeObject 不声明它；额外字段应被忽略不报错
    obj = FoeObject.model_validate(EXAMPLE_OBJECT)
    assert isinstance(obj, FoeObject)


def test_clause_ref_roundtrip():
    ref = ClauseRef(
        standard_code="JGJ 80-2016", clause_id="第4.1.1条", official_text="应设置防护栏杆。"
    )
    assert ref.paraphrase is None
    assert ref.source_raw == ""


def test_clause_ref_requires_core_fields():
    with pytest.raises(ValidationError):
        ClauseRef(standard_code="JGJ 80-2016")  # 缺 clause_id 与 official_text


def test_foe_report_request_wraps_analyses():
    req = FoeReportRequest(analyses=[FoeAnalysis(objects=[])], title="t")
    assert len(req.analyses) == 1
    assert req.title == "t"

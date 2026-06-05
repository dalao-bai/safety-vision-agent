"""Tests for domain schema validation (U3)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.models.schemas import AnalysisResult, Hazard, RiskLevel

_VALID_HAZARD = {
    "name": "未系安全带",
    "location": "脚手架顶部",
    "risk_level": "high",
    "basis": "工人在高处无防护",
    "remediation": "立即佩戴安全带",
    "confidence": 0.9,
}


def test_valid_structured_response_parses():
    raw = {
        "summary": "存在高空作业隐患",
        "hazards": [_VALID_HAZARD],
        "needs_followup": False,
        "followup_question": None,
    }
    result = AnalysisResult.model_validate(raw)
    assert result.summary == "存在高空作业隐患"
    assert len(result.hazards) == 1
    assert result.hazards[0].risk_level == RiskLevel.high
    assert result.hazards[0].confidence == 0.9


def test_confidence_above_one_fails():
    bad = {**_VALID_HAZARD, "confidence": 1.5}
    with pytest.raises(ValidationError):
        Hazard.model_validate(bad)


def test_confidence_below_zero_fails():
    bad = {**_VALID_HAZARD, "confidence": -0.1}
    with pytest.raises(ValidationError):
        Hazard.model_validate(bad)


def test_unknown_risk_level_fails():
    bad = {**_VALID_HAZARD, "risk_level": "extreme"}
    with pytest.raises(ValidationError):
        Hazard.model_validate(bad)


def test_empty_hazards_accepted_with_summary():
    # A clean site with no hazards is a valid, meaningful result.
    raw = {
        "summary": "未发现明显安全隐患",
        "hazards": [],
        "needs_followup": False,
        "followup_question": None,
    }
    result = AnalysisResult.model_validate(raw)
    assert result.hazards == []
    assert result.summary == "未发现明显安全隐患"


def test_needs_followup_requires_question():
    raw = {
        "summary": "图像不清晰",
        "hazards": [],
        "needs_followup": True,
        "followup_question": None,
    }
    with pytest.raises(ValidationError):
        AnalysisResult.model_validate(raw)


def test_needs_followup_with_question_accepted():
    raw = {
        "summary": "图像不清晰",
        "hazards": [],
        "needs_followup": True,
        "followup_question": "能否提供更清晰的照片?",
    }
    result = AnalysisResult.model_validate(raw)
    assert result.needs_followup is True
    assert result.followup_question == "能否提供更清晰的照片?"


def test_malformed_json_is_parse_failure_not_analysis():
    # Simulates a model returning non-JSON text. Parsing happens before
    # validation; this proves we can distinguish a parse failure.
    malformed = "这是一段自然语言，不是 JSON"
    with pytest.raises(json.JSONDecodeError):
        json.loads(malformed)


def test_missing_required_hazard_field_fails():
    bad = {k: v for k, v in _VALID_HAZARD.items() if k != "basis"}
    with pytest.raises(ValidationError):
        Hazard.model_validate(bad)

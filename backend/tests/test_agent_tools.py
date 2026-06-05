"""Tests for Agent tool registry and tool implementations (U6).

Tools are exercised independently of the Agent model. analyze_image uses a fake
VLM client; the three business tools run as deterministic transforms over a
prebuilt AnalysisResult.
"""

from __future__ import annotations

import json

import pytest

from app.agent.tools import (
    TOOL_DEFINITIONS,
    TOOL_NAMES,
    ToolContext,
    execute_tool,
)
from app.models.schemas import AnalysisResult
from app.services.responses_client import ResponsesResult


def _analysis() -> AnalysisResult:
    return AnalysisResult.model_validate(
        {
            "summary": "多处隐患",
            "hazards": [
                {
                    "name": "未系安全带",
                    "location": "脚手架顶部",
                    "risk_level": "high",
                    "basis": "工人高处作业无防护",
                    "remediation": "佩戴安全带并设置防护栏",
                    "confidence": 0.8,
                },
                {
                    "name": "临边无防护",
                    "location": "楼层边缘",
                    "risk_level": "critical",
                    "basis": "楼层临边缺少护栏",
                    "remediation": "安装临边防护栏杆",
                    "confidence": 0.95,
                },
                {
                    "name": "材料堆放杂乱",
                    "location": "通道处",
                    "risk_level": "low",
                    "basis": "通道被材料占用",
                    "remediation": "清理通道,规范堆放",
                    "confidence": 0.6,
                },
            ],
            "needs_followup": False,
            "followup_question": None,
        }
    )


def test_tool_definitions_match_v01_set():
    assert TOOL_NAMES == {
        "analyze_image",
        "explain_basis",
        "rank_risks",
        "suggest_remediation",
    }
    # Each definition has the function-tool shape Responses API expects.
    for d in TOOL_DEFINITIONS:
        assert d["type"] == "function"
        assert "name" in d and "parameters" in d


# --- analyze_image ---------------------------------------------------------

class _FakeVLMClient:
    def __init__(self, text):
        self._text = text

    def create(self, model, input_items, tools=None, text_format=None):
        return ResponsesResult(text=self._text, provider_id="resp_v", raw=None)


def test_analyze_image_calls_vlm_and_returns_summary(tmp_path):
    img = tmp_path / "x.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0bytes")
    valid = json.dumps(
        {
            "summary": "存在隐患",
            "hazards": [
                {
                    "name": "未系安全带",
                    "location": "顶部",
                    "risk_level": "high",
                    "basis": "无防护",
                    "remediation": "佩戴安全带",
                    "confidence": 0.9,
                }
            ],
            "needs_followup": False,
            "followup_question": None,
        },
        ensure_ascii=False,
    )
    ctx = ToolContext(
        image_path=str(img),
        image_mime="image/jpeg",
        vlm_client=_FakeVLMClient(valid),
        vlm_model="vlm",
    )
    result = execute_tool("analyze_image", {}, ctx)

    assert result.status == "success"
    assert result.output["available"] is True
    assert result.output["hazard_count"] == 1
    # The outcome is exposed for the orchestrator to persist raw response.
    assert ctx.last_analyzer_outcome is not None
    assert ctx.last_analyzer_outcome.ok is True
    # And ctx.analysis is populated for same-turn downstream tools.
    assert ctx.analysis is not None


def test_analyze_image_without_image_reports_unavailable():
    ctx = ToolContext()  # no image/client
    result = execute_tool("analyze_image", {}, ctx)
    assert result.status == "success"
    assert result.output["available"] is False


# --- explain_basis ---------------------------------------------------------

def test_explain_basis_returns_bases():
    ctx = ToolContext(analysis=_analysis())
    result = execute_tool("explain_basis", {}, ctx)
    assert result.status == "success"
    bases = result.output["bases"]
    assert len(bases) == 3
    assert bases[0]["name"] == "未系安全带"
    assert "basis" in bases[0] and "location" in bases[0]


def test_explain_basis_for_named_hazard():
    ctx = ToolContext(analysis=_analysis())
    result = execute_tool("explain_basis", {"hazard_name": "临边无防护"}, ctx)
    assert len(result.output["bases"]) == 1
    assert result.output["bases"][0]["name"] == "临边无防护"


# --- rank_risks ------------------------------------------------------------

def test_rank_risks_orders_by_severity_then_confidence():
    ctx = ToolContext(analysis=_analysis())
    result = execute_tool("rank_risks", {}, ctx)
    ranked = result.output["ranked"]
    # critical > high > low
    assert [r["name"] for r in ranked] == [
        "临边无防护",
        "未系安全带",
        "材料堆放杂乱",
    ]
    assert ranked[0]["rank"] == 1


# --- suggest_remediation ---------------------------------------------------

def test_suggest_remediation_returns_all():
    ctx = ToolContext(analysis=_analysis())
    result = execute_tool("suggest_remediation", {}, ctx)
    rem = result.output["remediations"]
    assert len(rem) == 3
    assert all("remediation" in r for r in rem)


def test_suggest_remediation_for_named_hazard():
    ctx = ToolContext(analysis=_analysis())
    result = execute_tool("suggest_remediation", {"hazard_name": "材料堆放杂乱"}, ctx)
    assert len(result.output["remediations"]) == 1
    assert result.output["remediations"][0]["name"] == "材料堆放杂乱"


# --- error paths -----------------------------------------------------------

@pytest.mark.parametrize(
    "tool", ["explain_basis", "rank_risks", "suggest_remediation"]
)
def test_followup_tools_without_analysis_report_unavailable(tool):
    ctx = ToolContext(analysis=None)
    result = execute_tool(tool, {}, ctx)
    assert result.status == "success"
    assert result.output["available"] is False
    assert "还没有" in result.output["message"]


def test_unknown_tool_is_recorded_as_error():
    ctx = ToolContext(analysis=_analysis())
    result = execute_tool("nonexistent_tool", {}, ctx)
    assert result.status == "error"
    assert "unknown tool" in result.error.lower()

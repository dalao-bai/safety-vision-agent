"""Agent tool registry and tool implementations (U6).

Defines the four v0.1 tools in the Responses API function-tool shape and
implements their handlers. `analyze_image` delegates to the VLM analyzer; the
other three are deterministic transforms over the stored AnalysisResult so they
do not trigger extra model calls in v0.1.

Tool execution here is independent of the Agent model — the orchestrator (U7)
owns the model loop and persistence. These handlers return plain dicts; the
caller records tool_calls.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from app.models.schemas import AnalysisResult
from app.services.responses_client import ResponsesClient
from app.services.vlm_analyzer import AnalyzerOutcome, analyze_image as run_vlm_analysis

# Ordering for risk severity, highest first.
_RISK_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@dataclass
class ToolContext:
    """Everything the tools need to run for one conversation turn.

    The orchestrator builds this and passes it to execute_tool. ``analysis`` is
    the latest stored AnalysisResult for the conversation (None if none yet).
    """

    analysis: AnalysisResult | None = None
    image_path: str | None = None
    image_mime: str | None = None
    vlm_client: ResponsesClient | None = None
    vlm_model: str | None = None
    user_question: str | None = None
    # Set by analyze_image so the orchestrator can persist the new analysis.
    last_analyzer_outcome: AnalyzerOutcome | None = None


class ToolError(Exception):
    """Raised for unknown tools or invalid tool invocation."""


# --- Tool definitions (Responses API function-tool shape) ------------------

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "analyze_image",
        "description": "分析当前上传的施工现场照片,识别安全隐患并返回结构化结果。首次分析或用户上传新照片时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "可选的分析侧重点或用户的具体问题。",
                }
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "explain_basis",
        "description": "解释已识别隐患的判断依据。当用户询问依据、理由或为什么不安全时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "hazard_name": {
                    "type": "string",
                    "description": "可选,指定要解释的某个隐患名称;省略则解释全部。",
                }
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "rank_risks",
        "description": "按严重程度对已识别的隐患排序。当用户询问哪个最严重或优先级时调用。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "suggest_remediation",
        "description": "针对已识别隐患给出整改建议。当用户询问如何整改、修复或处理时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "hazard_name": {
                    "type": "string",
                    "description": "可选,指定某个隐患;省略则给出全部隐患的整改建议。",
                }
            },
            "required": [],
            "additionalProperties": False,
        },
    },
]

TOOL_NAMES = {d["name"] for d in TOOL_DEFINITIONS}

_NO_ANALYSIS = {
    "available": False,
    "message": "当前对话还没有可用的隐患分析结果,请先上传照片进行分析。",
}


# --- Tool handlers ---------------------------------------------------------

def _tool_analyze_image(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    if not (ctx.vlm_client and ctx.vlm_model and ctx.image_path and ctx.image_mime):
        return {
            "available": False,
            "message": "没有可分析的照片,请先上传施工现场照片。",
        }

    question = args.get("question") or ctx.user_question
    outcome = run_vlm_analysis(
        ctx.vlm_client, ctx.vlm_model, ctx.image_path, ctx.image_mime, question
    )
    # Hand the full outcome back so the orchestrator can persist raw response.
    ctx.last_analyzer_outcome = outcome

    if not outcome.ok:
        return {"available": False, "message": f"图像分析失败: {outcome.error}"}

    result = outcome.result
    ctx.analysis = result  # downstream tools in the same turn can use it
    return {
        "available": True,
        "summary": result.summary,
        "hazard_count": len(result.hazards),
        "hazards": [h.model_dump(mode="json") for h in result.hazards],
        "needs_followup": result.needs_followup,
        "followup_question": result.followup_question,
    }


def _tool_explain_basis(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    if ctx.analysis is None:
        return _NO_ANALYSIS
    hazards = ctx.analysis.hazards
    name = args.get("hazard_name")
    if name:
        hazards = [h for h in hazards if h.name == name]
        if not hazards:
            return {"available": False, "message": f"未找到名为 {name!r} 的隐患。"}
    return {
        "available": True,
        "bases": [
            {"name": h.name, "location": h.location, "basis": h.basis}
            for h in hazards
        ],
    }


def _tool_rank_risks(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    if ctx.analysis is None:
        return _NO_ANALYSIS
    # Sort by risk severity, then by descending confidence as a tiebreaker.
    ranked = sorted(
        ctx.analysis.hazards,
        key=lambda h: (_RISK_ORDER.get(h.risk_level.value, 99), -h.confidence),
    )
    return {
        "available": True,
        "ranked": [
            {
                "rank": i + 1,
                "name": h.name,
                "risk_level": h.risk_level.value,
                "confidence": h.confidence,
            }
            for i, h in enumerate(ranked)
        ],
    }


def _tool_suggest_remediation(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    if ctx.analysis is None:
        return _NO_ANALYSIS
    hazards = ctx.analysis.hazards
    name = args.get("hazard_name")
    if name:
        hazards = [h for h in hazards if h.name == name]
        if not hazards:
            return {"available": False, "message": f"未找到名为 {name!r} 的隐患。"}
    return {
        "available": True,
        "remediations": [
            {"name": h.name, "remediation": h.remediation} for h in hazards
        ],
    }


_HANDLERS: dict[str, Callable[[dict[str, Any], ToolContext], dict[str, Any]]] = {
    "analyze_image": _tool_analyze_image,
    "explain_basis": _tool_explain_basis,
    "rank_risks": _tool_rank_risks,
    "suggest_remediation": _tool_suggest_remediation,
}


@dataclass
class ToolResult:
    """Outcome of executing one tool, including audit fields."""

    tool_name: str
    status: str  # 'success' | 'error'
    output: dict[str, Any] | None
    error: str | None
    duration_ms: int


def execute_tool(name: str, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Execute a tool by name and return a ToolResult with timing.

    Unknown tool names produce an error ToolResult rather than raising, so the
    orchestrator can record the failed call and continue gracefully.
    """
    start = time.monotonic()
    handler = _HANDLERS.get(name)
    if handler is None:
        duration = int((time.monotonic() - start) * 1000)
        return ToolResult(
            tool_name=name,
            status="error",
            output=None,
            error=f"unknown tool: {name!r}",
            duration_ms=duration,
        )
    try:
        output = handler(args or {}, ctx)
        duration = int((time.monotonic() - start) * 1000)
        return ToolResult(
            tool_name=name, status="success", output=output, error=None,
            duration_ms=duration,
        )
    except Exception as exc:  # noqa: BLE001 - record any handler error as audit data
        duration = int((time.monotonic() - start) * 1000)
        return ToolResult(
            tool_name=name, status="error", output=None, error=str(exc),
            duration_ms=duration,
        )

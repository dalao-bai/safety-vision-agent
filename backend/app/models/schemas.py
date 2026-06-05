"""Shared domain schemas for the v0.1 Agent (U3).

These Pydantic models define the contract enforced at backend boundaries:
VLM structured output, Agent tool results, and the chat API response. The
TypeScript mirror lives in frontend/src/types.ts and must stay aligned.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class RiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class Hazard(BaseModel):
    """One detected or suspected construction-site hazard."""

    name: str
    location: str
    risk_level: RiskLevel
    basis: str
    remediation: str
    confidence: float = Field(..., ge=0.0, le=1.0)


class AnalysisResult(BaseModel):
    """Structured hazard analysis returned by the VLM and stored per conversation."""

    summary: str
    hazards: list[Hazard] = Field(default_factory=list)
    needs_followup: bool = False
    followup_question: str | None = None

    @field_validator("followup_question")
    @classmethod
    def _followup_consistency(cls, v: str | None, info) -> str | None:
        # If the model says it needs follow-up, it must say what it needs.
        if info.data.get("needs_followup") and not v:
            raise ValueError(
                "followup_question is required when needs_followup is true"
            )
        return v


class ToolCallSummary(BaseModel):
    """Lightweight tool-call record surfaced to the frontend for local inspection."""

    tool_name: str
    status: str
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: int | None = None


class ChatResponse(BaseModel):
    """Response shape for the main conversation endpoint."""

    conversation_id: str
    answer: str
    analysis: AnalysisResult | None = None
    tool_calls: list[ToolCallSummary] = Field(default_factory=list)


class ApiError(BaseModel):
    """Controlled error body returned to the frontend."""

    error: str
    detail: str | None = None

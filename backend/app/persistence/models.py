from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Message:
    id: int
    session_id: str
    role: str
    content: str
    created_at: str


@dataclass
class ImageRecord:
    id: int
    session_id: str
    path: str
    scene: str
    status: str
    created_at: str


@dataclass
class Hazard:
    id: int
    image_id: int
    object_id: str
    status: str
    hazard_type_id: str | None
    bbox: list[int] | None
    reasoning_chain: list[dict[str, Any]] = field(default_factory=list)
    visual_evidence: str = ""
    rule_basis: str = ""
    evidence_sufficiency: str = ""
    confirmed: bool = False
    uncertainty_reason: str | None = None
    missing_evidence: str | None = None


@dataclass
class Correction:
    id: int
    image_id: int
    note: str
    intake_path: str
    created_at: str


@dataclass
class ToolCallRecord:
    """In-memory record built during a single handle_message call."""
    name: str
    args: dict
    result_summary: str
    duration_ms: float
    outcome: str   # "ok" | "error" | "guard_blocked"
    iteration: int


@dataclass
class ToolTrace:
    """Persisted row in the tool_traces table."""
    id: int
    session_id: str
    turn_user_msg_id: int
    iteration: int
    tool_name: str
    args_json: str
    result_summary: str # 工具返回值的截断摘要（最多200字符），用于事后排查，不存完整结果避免数据库膨胀。
    duration_ms: float
    outcome: str        # "ok" | "error" | "guard_blocked"
    loop_outcome: str   # "no_tool_calls" | "timeout" | "max_iter" | "pending"
    created_at: str

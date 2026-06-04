from typing import Any, TypedDict


class SafetyAgentState(TypedDict, total=False):
    conversation_id: str
    user_message: str
    file_id: str | None
    file_ids: list[str]
    image_path: str | None
    image_paths: list[str]
    selected_bbox: list[float] | None
    intent: str
    planner_mode: str
    step_count: int
    max_steps: int
    observations: list[dict]
    messages: list[dict]
    latest_analysis_id: str | None
    latest_fused_result: dict | None
    selected_hazard: dict | None
    tool_calls: list[dict]
    answer: str
    artifacts: dict[str, Any]
    errors: list[dict]

from typing import Any, TypedDict


class SafetyAgentState(TypedDict, total=False):
    conversation_id: str
    user_message: str
    file_id: str | None
    image_path: str | None
    selected_bbox: list[float] | None
    intent: str
    messages: list[dict]
    latest_analysis_id: str | None
    latest_fused_result: dict | None
    selected_hazard_index: int | None
    selected_hazard: dict | None
    tool_calls: list[dict]
    answer: str
    artifacts: dict[str, Any]
    errors: list[dict]

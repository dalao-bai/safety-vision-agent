from app.agent.graph import run_safety_agent
from app.models.schemas import ChatRequest, ChatResponse, FusedResult


class SafetyExpertAgent:
    """多轮隐患识别专家 Agent。"""

    async def handle(self, request: ChatRequest) -> ChatResponse:
        state = await run_safety_agent(
            {
                "conversation_id": request.conversation_id,
                "user_message": request.message,
                "file_id": getattr(request, "file_id", None),
                "image_path": request.image_path,
                "selected_bbox": request.selected_bbox,
            }
        )
        fused_json = state.get("latest_fused_result")
        return ChatResponse(
            conversation_id=state["conversation_id"],
            answer=state.get("answer", ""),
            latest_analysis_id=state.get("latest_analysis_id"),
            fused_result=FusedResult.model_validate(fused_json) if fused_json else None,
            tool_calls=state.get("tool_calls", []),
            artifacts=state.get("artifacts", {}),
            errors=state.get("errors", []),
        )

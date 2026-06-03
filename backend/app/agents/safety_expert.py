from uuid import uuid4

from app.models.schemas import ChatRequest, ChatResponse
from app.services.evidence_fusion import EvidenceFusionService
from app.services.rule_retriever import RuleRetriever
from app.services.vlm_client import VLMClient
from app.services.yolo_detector import YOLOHelmetDetector


class SafetyExpertAgent:
    '''多轮隐患识别专家 Agent。

    当前实现是可运行的编排骨架。真实 LLM 对话大脑、VLM API 地址和 YOLO
    YOLO API 由后续配置接入。
    '''

    async def handle(self, request: ChatRequest) -> ChatResponse:
        conversation_id = request.conversation_id or f"conv_{uuid4().hex}"
        tool_calls: list[dict] = []

        if not request.image_path:
            return ChatResponse(
                conversation_id=conversation_id,
                answer="请先上传或指定一张图片，我可以进行四口五临边隐患识别、安全帽检测和规则依据解释。",
                tool_calls=tool_calls,
            )

        rules = RuleRetriever().retrieve_for_prompt()
        tool_calls.append({"tool": "rule_retrieval_tool", "status": "ok", "rule_count": len(rules)})

        vlm_result = await VLMClient().analyze_image(
            image_path=request.image_path,
            question=request.message,
            candidate_rules=rules,
            target_bbox=request.selected_bbox,
        )
        tool_calls.append({"tool": "vlm_hazard_analysis_tool", "status": "ok"})

        yolo_result = YOLOHelmetDetector().detect(request.image_path)
        tool_calls.append({"tool": "yolo_helmet_detection_tool", "status": "ok"})

        fused = EvidenceFusionService().fuse(vlm_result, yolo_result)
        answer = self._build_answer(fused.summary, fused.recommendations)

        return ChatResponse(
            conversation_id=conversation_id,
            answer=answer,
            fused_result=fused,
            tool_calls=tool_calls,
        )

    def _build_answer(self, summary: str, recommendations: list[str]) -> str:
        if not summary:
            summary = "当前没有形成明确隐患结论。"
        if not recommendations:
            return summary
        return summary + "\n\n整改建议：\n" + "\n".join(f"- {item}" for item in recommendations)

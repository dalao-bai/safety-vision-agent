from app.models.schemas import FusedResult, VLMAnalysisResult, YOLODetectionResult
from app.services.uncertainty_resolver import UncertaintyResolver


class EvidenceFusionService:
    def fuse(self, vlm_result: VLMAnalysisResult, yolo_result: YOLODetectionResult) -> FusedResult:
        hazards = [item for item in vlm_result.objects if item.status == "confirmed_hazard"]
        uncertain_items = [item for item in vlm_result.objects if item.status == "uncertain"]
        uncertain_followups = UncertaintyResolver().build_followups(uncertain_items)

        recommendations: list[str] = []
        if hazards:
            recommendations.append("对已确认隐患区域进行现场复核，并按规则依据补齐防护措施。")
        if yolo_result.summary.get("no_helmet_count", 0) > 0:
            recommendations.append("立即纠正未佩戴安全帽人员，并加强现场个人防护检查。")
        if uncertain_items:
            recommendations.append("对证据不足项补充近景图片、现场尺寸或验收资料后复核。")

        summary_parts = []
        if hazards:
            summary_parts.append(f"发现 {len(hazards)} 处明确四口五临边隐患")
        if uncertain_items:
            summary_parts.append(f"{len(uncertain_items)} 处证据不足需要复核")
        if yolo_result.summary.get("no_helmet_count", 0) > 0:
            summary_parts.append(f"发现 {yolo_result.summary['no_helmet_count']} 名疑似未佩戴安全帽人员")

        summary = "；".join(summary_parts) + "。" if summary_parts else "未形成明确隐患结论。"

        return FusedResult(
            hazards=hazards,
            detections=yolo_result.detections,
            uncertain_items=uncertain_items,
            uncertain_followups=uncertain_followups,
            summary=summary,
            recommendations=recommendations,
        )

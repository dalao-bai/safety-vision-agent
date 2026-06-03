from app.models.schemas import ReportRequest, ReportResponse


class ReportGenerator:
    def generate(self, request: ReportRequest) -> ReportResponse:
        lines = [f"# {request.title}", ""]
        lines.append(f"会话 ID：{request.conversation_id}")
        lines.append("")

        if request.fused_result is None:
            lines.append("当前没有可用于生成报告的融合结果。")
            return ReportResponse(title=request.title, markdown="\n".join(lines))

        result = request.fused_result
        lines.append("## 总结")
        lines.append(result.summary or "暂无总结。")
        lines.append("")

        lines.append("## 明确隐患")
        if result.hazards:
            for index, hazard in enumerate(result.hazards, start=1):
                lines.append(f"{index}. {hazard.object_name}：{hazard.hazard_type or hazard.status}")
                lines.append(f"   - 证据：{hazard.visual_evidence}")
                lines.append(f"   - 规则：{hazard.rule}")
        else:
            lines.append("未发现明确四口五临边隐患。")
        lines.append("")

        lines.append("## 整改建议")
        if result.recommendations:
            for item in result.recommendations:
                lines.append(f"- {item}")
        else:
            lines.append("暂无整改建议。")

        return ReportResponse(title=request.title, markdown="\n".join(lines))

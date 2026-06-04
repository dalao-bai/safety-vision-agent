from app.agent.prompts import NO_IMAGE_PROMPT, TOOL_FAILURE_PROMPT
from app.models.schemas import FusedResult


def build_analysis_answer(fused: FusedResult | None) -> str:
    if fused is None:
        return TOOL_FAILURE_PROMPT
    lines = [fused.summary or "当前没有形成明确隐患结论。"]
    if fused.hazards:
        lines.append("")
        lines.append("风险优先级：")
        for index, hazard in enumerate(fused.hazards, start=1):
            source = f"（{hazard.source_label}）" if hazard.source_label else ""
            risk = _risk_text(hazard.risk_level, hazard.risk_score)
            lines.append(f"{index}. {source}{hazard.object_name}：{hazard.hazard_type or hazard.status}，{risk}")
            lines.append(f"   证据：{hazard.visual_evidence}")
            lines.append(f"   依据：{hazard.rule}")
            if hazard.risk_reasons:
                lines.append(f"   排序原因：{'、'.join(hazard.risk_reasons)}")
    if fused.uncertain_items:
        lines.append("")
        lines.append("证据不足项：")
        for item in fused.uncertain_items:
            source = f"（{item.source_label}）" if item.source_label else ""
            lines.append(f"- {source}{item.object_name}：{item.missing_evidence or item.uncertainty_reason or '需要补充证据'}")
    if fused.uncertain_followups:
        lines.append("")
        lines.append("建议补充证据：")
        for item in fused.uncertain_followups:
            lines.append(f"- {item.follow_up_question}；{item.capture_suggestion}")
    if fused.recommendations:
        lines.append("")
        lines.append("整改建议：")
        lines.extend(f"- {item}" for item in fused.recommendations)
    return "\n".join(lines)


def build_rule_answer(result: dict) -> str:
    if result.get("error") == "hazard_index_out_of_range":
        return f"当前只有 {result.get('hazard_count', 0)} 个明确隐患，无法找到你说的第 {result.get('index', 0) + 1} 个。"
    hazard = result.get("hazard") or {}
    source = f"（{hazard.get('source_label')}）" if hazard.get("source_label") else ""
    risk = _risk_text(hazard.get("risk_level"), hazard.get("risk_score"))
    return (
        f"第 {result.get('index', 0) + 1} 个隐患是{source}“{hazard.get('object_name')}”。\n"
        f"风险：{risk}\n"
        f"判断依据：{hazard.get('rule') or '当前结果里没有记录明确规则依据。'}\n"
        f"视觉证据：{hazard.get('visual_evidence') or '当前结果里没有记录视觉证据。'}"
    )


def build_evidence_gap_answer(fused: FusedResult | None) -> str:
    if not fused:
        return NO_IMAGE_PROMPT
    if not fused.uncertain_followups and not fused.uncertain_items:
        return "当前结果里没有标记为证据不足的隐患项。如果你担心某个部位，请指出第几个隐患或重新补拍近景图。"
    lines = ["建议补充这些证据："]
    for item in fused.uncertain_followups:
        lines.append(f"- {item.object_name}：{item.follow_up_question}；{item.capture_suggestion}")
    for item in fused.uncertain_items:
        source = f"（{item.source_label}）" if item.source_label else ""
        lines.append(f"- {source}{item.object_name}：{item.missing_evidence or item.uncertainty_reason or '补充近景和周边环境图'}")
    return "\n".join(lines)


def build_final_answer(state: dict) -> str:
    if state.get("answer"):
        return state["answer"]
    fused_json = state.get("latest_fused_result")
    if fused_json:
        return build_analysis_answer(FusedResult.model_validate(fused_json))
    return NO_IMAGE_PROMPT


def _risk_text(level: str | None, score: int | None) -> str:
    if level and score is not None:
        return f"{level}（{score}）"
    if level:
        return level
    if score is not None:
        return f"风险分 {score}"
    return "风险待评估"

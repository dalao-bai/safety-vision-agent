from dataclasses import dataclass, field
from typing import Any

from app.core.config import get_settings


APPROVED_ACTIONS = {
    "memory_lookup",
    "analyze_images",
    "rule_lookup",
    "evidence_gap",
    "risk_score",
    "create_remediation",
    "generate_report",
    "final_answer",
}


@dataclass(frozen=True)
class AgentAction:
    name: str
    reason: str
    args: dict[str, Any] = field(default_factory=dict)


def max_agent_steps() -> int:
    return 10


def planner_mode() -> str:
    settings = get_settings()
    if settings.llm_api_base_url and settings.llm_model_name:
        return "llm_configured_deterministic_fallback"
    return "deterministic_fallback"


class DeterministicReActPlanner:
    """A bounded fallback planner that uses the same actions as an LLM planner."""

    def next_action(self, state: dict) -> AgentAction:
        completed = {item.get("action") for item in state.get("observations", []) if item.get("status") == "ok"}
        failed = {item.get("action") for item in state.get("observations", []) if item.get("status") == "error"}
        text = state.get("user_message", "")
        has_images = bool(state.get("file_ids") or state.get("file_id") or state.get("image_paths") or state.get("image_path"))
        has_result = bool(state.get("latest_fused_result"))
        wants_report = _contains(text, ["报告", "报表", "导出"])
        wants_remediation_record = _contains(text, ["创建整改", "生成整改任务", "创建任务", "指派整改", "整改任务"])
        wants_remediation_advice = _contains(text, ["整改", "怎么处理", "怎么改"])
        wants_rule = _contains(text, ["依据", "规则", "规范", "为什么", "原因"])
        wants_gap = _contains(text, ["补拍", "补什么", "证据不足", "还需要什么"])
        wants_ranking = _contains(text, ["比较", "排序", "优先", "最严重", "严重程度", "风险最高", "哪个最"])

        if not has_result and "memory_lookup" not in completed and not has_images:
            return AgentAction("memory_lookup", "检查会话中是否已有可复用的分析结果。")

        if not has_result and has_images and "analyze_images" not in completed and "analyze_images" not in failed:
            return AgentAction("analyze_images", "需要先分析用户提供的图片证据。")

        if not state.get("latest_fused_result"):
            return AgentAction("final_answer", "没有图片或历史分析结果，无法继续调用安全工具。")

        if "risk_score" not in completed:
            reason = "用户需要比较、排序或风险优先级，需要先计算风险分值。" if (wants_ranking or wants_report) else "最终安全结论需要带风险等级。"
            return AgentAction("risk_score", reason)

        if wants_rule and "rule_lookup" not in completed:
            return AgentAction("rule_lookup", "用户询问依据，需要读取隐患和规则上下文。")

        if wants_gap and "evidence_gap" not in completed:
            return AgentAction("evidence_gap", "用户询问证据不足或补拍建议。")

        if wants_remediation_record and "create_remediation" not in completed:
            return AgentAction("create_remediation", "用户明确要求创建整改任务。")

        if wants_report and "generate_report" not in completed:
            return AgentAction("generate_report", "用户明确要求生成报告。")

        if wants_remediation_advice and not wants_remediation_record:
            return AgentAction("final_answer", "用户只需要整改建议，不应自动创建整改任务。")

        return AgentAction("final_answer", "已有足够工具观察，可以生成最终回答。")


def _contains(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)

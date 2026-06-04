from uuid import uuid4

from app.agent.prompts import NO_IMAGE_PROMPT, TOOL_FAILURE_PROMPT
from app.agent.router import classify_intent, selected_hazard_index
from app.agent.tools import answer_rule_basis_tool, create_remediation_tool, generate_report_tool, run_image_analysis_tool
from app.db import repositories
from app.models.schemas import FusedResult
from app.services.memory import latest_result_context, recent_messages


def _build_analysis_answer(fused: FusedResult | None) -> str:
    if fused is None:
        return TOOL_FAILURE_PROMPT
    lines = [fused.summary or "当前没有形成明确隐患结论。"]
    if fused.hazards:
        lines.append("")
        lines.append("明确隐患：")
        for index, hazard in enumerate(fused.hazards, start=1):
            lines.append(f"{index}. {hazard.object_name}：{hazard.hazard_type or hazard.status}。依据：{hazard.rule}")
    if fused.uncertain_followups:
        lines.append("")
        lines.append("需要补充证据：")
        for item in fused.uncertain_followups:
            lines.append(f"- {item.follow_up_question}；{item.capture_suggestion}")
    if fused.recommendations:
        lines.append("")
        lines.append("整改建议：")
        lines.extend(f"- {item}" for item in fused.recommendations)
    return "\n".join(lines)


def load_context(state: dict) -> dict:
    conversation_id = state.get("conversation_id") or f"conv_{uuid4().hex}"
    conversation = repositories.get_or_create_conversation(conversation_id)
    latest = latest_result_context(conversation.id)
    return {
        **state,
        "conversation_id": conversation.id,
        "messages": recent_messages(conversation.id),
        "latest_analysis_id": latest.get("analysis", {}).get("id"),
        "latest_fused_result": latest.get("fused_result"),
        "tool_calls": [],
        "artifacts": {},
        "errors": [],
    }


def classify(state: dict) -> dict:
    has_image = bool(state.get("file_id") or state.get("image_path"))
    intent = classify_intent(state["user_message"], state["conversation_id"], has_image)
    return {**state, "intent": intent, "selected_hazard_index": selected_hazard_index(state["user_message"])}


def need_image(state: dict) -> dict:
    return {**state, "answer": NO_IMAGE_PROMPT}


async def analyze_image(state: dict) -> dict:
    result = await run_image_analysis_tool(
        conversation_id=state["conversation_id"],
        message=state["user_message"],
        file_id=state.get("file_id"),
        image_path=state.get("image_path"),
        selected_bbox=state.get("selected_bbox"),
    )
    fused = result.get("fused_result")
    artifacts = {**state.get("artifacts", {}), "analysis_id": result.get("analysis_id")}
    if result.get("error"):
        errors = [*state.get("errors", []), {"code": result["error"], "analysis_id": result.get("analysis_id")}]
    else:
        errors = state.get("errors", [])
    return {
        **state,
        "latest_analysis_id": result.get("analysis_id"),
        "latest_fused_result": fused.model_dump() if hasattr(fused, "model_dump") else None,
        "tool_calls": [*state.get("tool_calls", []), *result.get("tool_calls", [])],
        "answer": _build_analysis_answer(fused),
        "artifacts": artifacts,
        "errors": errors,
    }


def answer_from_memory(state: dict) -> dict:
    latest = latest_result_context(state["conversation_id"])
    if not latest:
        return need_image(state)
    fused = FusedResult.model_validate(latest["fused_result"])
    answer = _build_analysis_answer(fused)
    return {
        **state,
        "latest_analysis_id": latest["analysis"]["id"],
        "latest_fused_result": fused.model_dump(),
        "answer": answer,
    }


def answer_rule_basis(state: dict) -> dict:
    result = answer_rule_basis_tool(state["conversation_id"], state["user_message"])
    if not result:
        return need_image(state)
    if result.get("error") == "hazard_index_out_of_range":
        return {**state, "answer": f"当前只有 {result.get('hazard_count', 0)} 个明确隐患，无法找到你说的第 {result.get('index', 0) + 1} 个。"}
    hazard = result["hazard"]
    answer = (
        f"第 {result['index'] + 1} 个隐患是“{hazard.get('object_name')}”。\n"
        f"判断依据：{hazard.get('rule') or '当前结果里没有记录明确规则依据。'}\n"
        f"视觉证据：{hazard.get('visual_evidence') or '当前结果里没有记录视觉证据。'}"
    )
    return {
        **state,
        "latest_analysis_id": result["analysis"]["id"],
        "selected_hazard": hazard,
        "latest_fused_result": result["fused_result"],
        "tool_calls": [*state.get("tool_calls", []), *result.get("tool_calls", [])],
        "answer": answer,
    }


def answer_evidence_gap(state: dict) -> dict:
    latest = latest_result_context(state["conversation_id"])
    if not latest:
        return need_image(state)
    fused = FusedResult.model_validate(latest["fused_result"])
    if not fused.uncertain_followups:
        return {
            **state,
            "latest_analysis_id": latest["analysis"]["id"],
            "latest_fused_result": fused.model_dump(),
            "answer": "当前结果里没有标记为证据不足的隐患项。如果你担心某个部位，请指出第几个隐患或重新补拍近景图。",
        }
    lines = ["建议补充这些证据："]
    for item in fused.uncertain_followups:
        lines.append(f"- {item.object_name}：{item.follow_up_question}；{item.capture_suggestion}")
    return {**state, "latest_analysis_id": latest["analysis"]["id"], "latest_fused_result": fused.model_dump(), "answer": "\n".join(lines)}


def create_remediation(state: dict) -> dict:
    result = create_remediation_tool(state["conversation_id"], state["user_message"])
    if not result:
        return need_image(state)
    if result.get("error") == "hazard_index_out_of_range":
        return {**state, "answer": f"当前只有 {result.get('hazard_count', 0)} 个明确隐患，无法为该序号创建整改任务。"}
    task = result["remediation_task"]
    answer = f"已创建整改任务：{task['title']}。\n整改要求：{task['recommendation']}"
    return {
        **state,
        "latest_analysis_id": result["analysis"]["id"],
        "latest_fused_result": result["fused_result"],
        "selected_hazard": result["hazard"],
        "artifacts": {**state.get("artifacts", {}), "remediation_task": task},
        "answer": answer,
    }


def generate_report(state: dict) -> dict:
    result = generate_report_tool(state["conversation_id"])
    if not result:
        return need_image(state)
    report = result["report"]
    return {
        **state,
        "latest_analysis_id": result["analysis"]["id"],
        "latest_fused_result": result["fused_result"],
        "artifacts": {**state.get("artifacts", {}), "report": report, "report_record": result["report_record"]},
        "answer": f"已生成报告：{report['title']}\n\n{report['markdown']}",
    }


def persist_turn(state: dict) -> dict:
    repositories.add_message(state["conversation_id"], "user", state["user_message"])
    repositories.add_message(state["conversation_id"], "assistant", state.get("answer", ""))
    return state

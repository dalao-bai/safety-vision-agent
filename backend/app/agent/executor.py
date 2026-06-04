from uuid import uuid4

from app.agent.formatter import build_evidence_gap_answer, build_final_answer, build_rule_answer
from app.agent.prompts import TOOL_FAILURE_PROMPT
from app.agent.planner import APPROVED_ACTIONS, AgentAction, DeterministicReActPlanner, max_agent_steps, planner_mode
from app.agent.tools import (
    answer_rule_basis_tool,
    create_remediation_tool,
    generate_report_tool,
    memory_lookup_tool,
    run_multi_image_analysis_tool,
    score_risk_tool,
)
from app.db import repositories
from app.models.schemas import FusedResult
from app.services.memory import recent_messages


LEGACY_INTENTS = {
    "analyze_images": "analyze",
    "rule_lookup": "rule_basis",
    "evidence_gap": "evidence_gap",
    "create_remediation": "remediation",
    "generate_report": "report",
}


class ReActSafetyAgent:
    def __init__(self, planner: DeterministicReActPlanner | None = None, max_steps: int | None = None) -> None:
        self.planner = planner or DeterministicReActPlanner()
        self.max_steps = max_steps or max_agent_steps()

    async def run(self, state: dict) -> dict:
        current = self._load_context(state)
        while current["step_count"] < current["max_steps"]:
            action = self.planner.next_action(current)
            if action.name not in APPROVED_ACTIONS:
                current = self._append_error(current, "unapproved_action", {"action": action.name})
                break
            if action.name == "final_answer":
                current["answer"] = build_final_answer(current)
                if not current.get("latest_fused_result"):
                    current["intent"] = "need_image"
                elif current.get("intent"):
                    pass
                else:
                    current["intent"] = "memory_answer"
                break
            current = await self._run_action(current, action)
            if current.get("stop_requested"):
                break

        if current["step_count"] >= current["max_steps"] and not current.get("answer"):
            current["answer"] = f"本轮已达到最多 {current['max_steps']} 个工具步骤。下面是已完成部分：\n\n{build_final_answer(current)}"
            current = self._append_error(current, "max_steps_reached", {"max_steps": current["max_steps"]})

        repositories.add_message(current["conversation_id"], "user", current["user_message"])
        repositories.add_message(current["conversation_id"], "assistant", current.get("answer", ""))
        current.pop("stop_requested", None)
        return current

    def _load_context(self, state: dict) -> dict:
        conversation_id = state.get("conversation_id") or f"conv_{uuid4().hex}"
        conversation = repositories.get_or_create_conversation(conversation_id)
        file_ids = list(state.get("file_ids") or [])
        if state.get("file_id") and state["file_id"] not in file_ids:
            file_ids.insert(0, state["file_id"])
        image_paths = list(state.get("image_paths") or [])
        if state.get("image_path") and state["image_path"] not in image_paths:
            image_paths.insert(0, state["image_path"])
        return {
            **state,
            "conversation_id": conversation.id,
            "file_ids": file_ids,
            "image_paths": image_paths,
            "messages": recent_messages(conversation.id),
            "planner_mode": planner_mode(),
            "step_count": 0,
            "max_steps": self.max_steps,
            "observations": [],
            "tool_calls": [],
            "artifacts": {},
            "errors": [],
        }

    async def _run_action(self, state: dict, action: AgentAction) -> dict:
        next_state = {**state, "step_count": state["step_count"] + 1}
        if action.name != "risk_score":
            next_state["intent"] = LEGACY_INTENTS.get(action.name, action.name)
        try:
            if action.name == "memory_lookup":
                result = memory_lookup_tool(state["conversation_id"])
                if result:
                    next_state["latest_analysis_id"] = result["analysis"]["id"]
                    next_state["latest_fused_result"] = result["fused_result"]
                return self._observe(next_state, action, "ok", {"found": bool(result)})

            if action.name == "analyze_images":
                result = await run_multi_image_analysis_tool(
                    conversation_id=state["conversation_id"],
                    message=state["user_message"],
                    file_ids=state.get("file_ids", []),
                    image_paths=state.get("image_paths", []),
                    selected_bbox=state.get("selected_bbox"),
                )
                next_state["tool_calls"] = [*state.get("tool_calls", []), *result.get("tool_calls", [])]
                if result.get("error"):
                    next_state["latest_analysis_id"] = result.get("analysis_id")
                    next_state["artifacts"] = {**state.get("artifacts", {}), "analyses": result.get("analyses", [])}
                    next_state["answer"] = TOOL_FAILURE_PROMPT
                    next_state = self._append_error(next_state, result["error"], {})
                    return self._observe(next_state, action, "error", {"error": result["error"]})
                fused = result.get("fused_result")
                next_state["latest_analysis_id"] = result.get("analysis_id")
                next_state["latest_fused_result"] = fused.model_dump() if hasattr(fused, "model_dump") else fused
                next_state["artifacts"] = {**state.get("artifacts", {}), "analyses": result.get("analyses", [])}
                for error in result.get("errors", []):
                    next_state = self._append_error(next_state, error.get("code", "tool_failed"), {key: value for key, value in error.items() if key != "code"})
                return self._observe(next_state, action, "ok", {"analysis_count": len(result.get("analyses", []))})

            if action.name == "risk_score":
                result = score_risk_tool(state.get("latest_fused_result") or {})
                next_state["latest_fused_result"] = result["fused_result"]
                if state.get("latest_analysis_id"):
                    repositories.save_fused_result(state["latest_analysis_id"], result["fused_result"])
                return self._observe(next_state, action, "ok", {"hazard_count": len(result["fused_result"].get("hazards") or [])})

            if action.name == "rule_lookup":
                result = answer_rule_basis_tool(state["conversation_id"], state["user_message"])
                next_state["tool_calls"] = [*state.get("tool_calls", []), *result.get("tool_calls", [])]
                if not result:
                    next_state["answer"] = build_final_answer(state)
                else:
                    next_state["latest_analysis_id"] = result.get("analysis", {}).get("id")
                    if result.get("fused_result"):
                        next_state["latest_fused_result"] = result.get("fused_result")
                    next_state["selected_hazard"] = result.get("hazard")
                    next_state["answer"] = build_rule_answer(result)
                return self._observe(next_state, action, "ok", {"answered": bool(result)})

            if action.name == "evidence_gap":
                fused = FusedResult.model_validate(state["latest_fused_result"]) if state.get("latest_fused_result") else None
                next_state["answer"] = build_evidence_gap_answer(fused)
                return self._observe(next_state, action, "ok", {"answered": True})

            if action.name == "create_remediation":
                result = create_remediation_tool(state["conversation_id"], state["user_message"])
                if not result:
                    next_state["answer"] = build_final_answer(state)
                elif result.get("error") == "hazard_index_out_of_range":
                    next_state["answer"] = f"当前只有 {result.get('hazard_count', 0)} 个明确隐患，无法为该序号创建整改任务。"
                else:
                    task = result["remediation_task"]
                    next_state["latest_analysis_id"] = result["analysis"]["id"]
                    next_state["latest_fused_result"] = result["fused_result"]
                    next_state["selected_hazard"] = result["hazard"]
                    next_state["artifacts"] = {**state.get("artifacts", {}), "remediation_task": task}
                    next_state["answer"] = f"已创建整改任务：{task['title']}。\n整改要求：{task['recommendation']}"
                return self._observe(next_state, action, "ok", {"created": bool(next_state.get("artifacts", {}).get("remediation_task"))})

            if action.name == "generate_report":
                result = generate_report_tool(state["conversation_id"], state.get("latest_fused_result"))
                if not result:
                    next_state["answer"] = build_final_answer(state)
                    return self._observe(next_state, action, "error", {"error": "missing_analysis"})
                report = result["report"]
                next_state["latest_analysis_id"] = result["analysis"]["id"]
                next_state["latest_fused_result"] = result["fused_result"]
                next_state["artifacts"] = {**state.get("artifacts", {}), "report": report, "report_record": result["report_record"]}
                next_state["answer"] = f"已生成报告：{report['title']}\n\n{report['markdown']}"
                return self._observe(next_state, action, "ok", {"report_id": result["report_record"]["id"]})

        except Exception as exc:
            next_state = self._append_error(next_state, "tool_failed", {"action": action.name, "error": str(exc)})
            return self._observe(next_state, action, "error", {"error": str(exc)})

        return self._observe(next_state, action, "error", {"error": "unsupported_action"})

    def _observe(self, state: dict, action: AgentAction, status: str, observation: dict) -> dict:
        record = repositories.create_tool_call(
            state["conversation_id"],
            state.get("latest_analysis_id"),
            f"react_{action.name}",
            status,
            {"step_index": state["step_count"], "planner_summary": action.reason, "args": action.args},
            observation,
            None,
        )
        trace = {
            "tool": record.tool_name,
            "status": record.status,
            "input": record.input_json,
            "output": record.output_json,
            "observation": record.output_json,
            "latency_ms": record.latency_ms,
        }
        return {
            **state,
            "tool_calls": [*state.get("tool_calls", []), trace],
            "observations": [
                *state.get("observations", []),
                {"action": action.name, "status": status, "observation": observation, "planner_summary": action.reason},
            ],
        }

    def _append_error(self, state: dict, code: str, detail: dict) -> dict:
        return {**state, "errors": [*state.get("errors", []), {"code": code, **detail}]}

"""Agent orchestrator: bounded tool-calling loop (U7).

Drives the Agent model with Responses API tool calling. Each turn:
  1. Build context (system prompt + history + tool context).
  2. Call AGENT_MODEL with the tool definitions.
  3. If the model emits function calls, execute them, persist each tool call,
     append their outputs, and loop.
  4. When the model returns a final text answer (or the iteration cap is hit),
     persist the assistant message and return.

Raw Agent model responses and errors are persisted to model_responses for
v0.1 audit. The loop is bounded by max_iterations to prevent runaway calls.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from app.agent.context import build_context
from app.agent.tools import TOOL_DEFINITIONS, ToolContext, execute_tool
from app.db import repositories as repo
from app.models.schemas import AnalysisResult, ToolCallSummary
from app.services.responses_client import ResponsesClient


@dataclass
class OrchestratorResult:
    """Outcome of one orchestrated agent turn."""

    answer: str
    analysis: AnalysisResult | None
    tool_calls: list[ToolCallSummary] = field(default_factory=list)


def _extract_function_calls(response: Any) -> list[dict[str, Any]]:
    """Pull function-call items out of a Responses API response.

    Each returned dict has: call_id, name, arguments (parsed dict). Tolerates
    the SDK object shape and a plain-dict shape (used by tests).
    """
    calls: list[dict[str, Any]] = []
    output = response.get("output") if isinstance(response, dict) else getattr(response, "output", None)
    for item in output or []:
        item_type = item.get("type") if isinstance(item, dict) else getattr(item, "type", None)
        if item_type != "function_call":
            continue
        if isinstance(item, dict):
            name = item.get("name")
            call_id = item.get("call_id")
            raw_args = item.get("arguments")
        else:
            name = getattr(item, "name", None)
            call_id = getattr(item, "call_id", None)
            raw_args = getattr(item, "arguments", None)
        try:
            parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
        except json.JSONDecodeError:
            parsed_args = {}
        calls.append({"call_id": call_id, "name": name, "arguments": parsed_args})
    return calls


def _extract_text(response: Any) -> str:
    """Pull the assistant's final text from a Responses API response."""
    if isinstance(response, dict):
        text = response.get("output_text")
        if text:
            return text
        parts: list[str] = []
        for item in response.get("output", []) or []:
            if item.get("type") == "message" or item.get("content"):
                for block in item.get("content", []) or []:
                    if block.get("text"):
                        parts.append(block["text"])
        return "".join(parts)
    # SDK object
    text = getattr(response, "output_text", None)
    if text:
        return text
    parts = []
    for item in getattr(response, "output", []) or []:
        for block in getattr(item, "content", []) or []:
            block_text = getattr(block, "text", None)
            if block_text:
                parts.append(block_text)
    return "".join(parts)


def _raw_text(response: Any) -> str:
    """Best-effort serialization of a response for audit storage."""
    try:
        if isinstance(response, dict):
            return json.dumps(response, ensure_ascii=False, default=str)
        if hasattr(response, "model_dump_json"):
            return response.model_dump_json()
        return str(response)
    except Exception:  # noqa: BLE001
        return str(response)


def run_turn(
    conn: sqlite3.Connection,
    conversation_id: str,
    user_message: str,
    agent_client: ResponsesClient,
    agent_model: str,
    vlm_client: ResponsesClient,
    vlm_model: str,
    max_iterations: int = 5,
    new_image_uploaded: bool = False,
) -> OrchestratorResult:
    """Run one bounded tool-calling turn and return the assistant answer.

    The user message must already be persisted by the caller before this runs
    so it appears in the loaded history. ``new_image_uploaded`` tells the
    context builder that an image arrived this turn so the Agent is instructed
    to analyze it (the model cannot see images directly).
    """
    loaded = build_context(
        conn, conversation_id, user_message, vlm_client, vlm_model,
        new_image_uploaded=new_image_uploaded,
    )
    input_items = loaded.input_items
    tool_ctx = loaded.tool_context

    tool_summaries: list[ToolCallSummary] = []

    for _iteration in range(max_iterations):
        try:
            response = agent_client.raw_create(
                model=agent_model,
                input=input_items,
                tools=TOOL_DEFINITIONS,
            )
        except Exception as exc:  # noqa: BLE001 - persist and surface controlled error
            repo.save_model_response(
                conn, conversation_id, model_role="agent", status="error",
                error=str(exc),
            )
            answer = "抱歉,调用模型时出现错误,请稍后重试。"
            repo.add_message(conn, conversation_id, "assistant", answer)
            return OrchestratorResult(
                answer=answer, analysis=tool_ctx.analysis, tool_calls=tool_summaries
            )

        provider_id = (
            response.get("id") if isinstance(response, dict)
            else getattr(response, "id", None)
        )
        repo.save_model_response(
            conn, conversation_id, model_role="agent", status="success",
            provider_id=provider_id, raw_text=_raw_text(response),
        )

        function_calls = _extract_function_calls(response)
        if not function_calls:
            # Final answer.
            answer = _extract_text(response) or "(模型未返回文本)"
            repo.add_message(conn, conversation_id, "assistant", answer)
            return OrchestratorResult(
                answer=answer, analysis=tool_ctx.analysis, tool_calls=tool_summaries
            )

        # The model produced function calls; append them, execute, feed results back.
        for fc in function_calls:
            input_items.append({
                "type": "function_call",
                "call_id": fc["call_id"],
                "name": fc["name"],
                "arguments": json.dumps(fc["arguments"], ensure_ascii=False),
            })
            tool_result = execute_tool(fc["name"], fc["arguments"], tool_ctx)

            # If analyze_image ran, persist the new analysis + raw VLM response.
            if fc["name"] == "analyze_image" and tool_ctx.last_analyzer_outcome:
                outcome = tool_ctx.last_analyzer_outcome
                repo.save_model_response(
                    conn, conversation_id, model_role="vlm",
                    status="success" if outcome.ok else "error",
                    provider_id=outcome.provider_id, raw_text=outcome.raw_text,
                    error=outcome.error,
                )
                if outcome.ok and outcome.result:
                    image_row = repo.get_latest_image(conn, conversation_id)
                    repo.save_analysis_result(
                        conn, conversation_id, outcome.result.model_dump(mode="json"),
                        image_id=image_row["id"] if image_row else None,
                    )

            repo.save_tool_call(
                conn, conversation_id, tool_name=tool_result.tool_name,
                status=tool_result.status, input_data=fc["arguments"],
                output_data=tool_result.output, error=tool_result.error,
                duration_ms=tool_result.duration_ms, call_id=fc["call_id"],
            )
            tool_summaries.append(ToolCallSummary(
                tool_name=tool_result.tool_name, status=tool_result.status,
                input=fc["arguments"], output=tool_result.output,
                error=tool_result.error, duration_ms=tool_result.duration_ms,
            ))
            input_items.append({
                "type": "function_call_output",
                "call_id": fc["call_id"],
                "output": json.dumps(
                    tool_result.output if tool_result.status == "success"
                    else {"error": tool_result.error},
                    ensure_ascii=False,
                ),
            })

    # Iteration cap reached without a final answer.
    repo.save_model_response(
        conn, conversation_id, model_role="agent", status="error",
        error=f"exceeded max tool iterations ({max_iterations})",
    )
    answer = "抱歉,处理这个请求时步骤过多,已停止。请尝试更具体的提问。"
    repo.add_message(conn, conversation_id, "assistant", answer)
    return OrchestratorResult(
        answer=answer, analysis=tool_ctx.analysis, tool_calls=tool_summaries
    )

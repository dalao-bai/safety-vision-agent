"""Agent orchestrator: LangGraph create_react_agent loop (v0.2).

Drives the agent with LangGraph's create_react_agent. Each turn:
  1. Build context (system prompt + preference memory + history) as BaseMessages.
  2. Bind per-request tools via make_tools().
  3. Invoke the agent executor with a recursion limit derived from max_iterations.
  4. Persist the assistant answer and return OrchestratorResult.

Tool execution, audit logging, and DB persistence of tool calls are handled by
AuditCallbackHandler and the @tool implementations in tools.py. The hand-written
Responses API loop is replaced entirely.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from langgraph.errors import GraphRecursionError
from langgraph.prebuilt import create_react_agent

from app.agent.audit import AuditCallbackHandler
from app.agent.context import build_context
from app.agent.llm import make_agent_llm
from app.agent.tools import make_tools
from app.core.config import Settings
from app.db import repositories as repo
from app.models.schemas import AnalysisResult, ToolCallSummary
from app.services.responses_client import ResponsesClient


@dataclass
class OrchestratorResult:
    """Outcome of one orchestrated agent turn."""

    answer: str
    analysis: AnalysisResult | None
    tool_calls: list[ToolCallSummary] = field(default_factory=list)


def run_turn(
    conn: sqlite3.Connection,
    conversation_id: str,
    user_message: str,
    vlm_client: ResponsesClient,   # passed to make_tools for analyze_image
    vlm_model: str,                # passed to make_tools for analyze_image
    settings: Settings,            # used by make_agent_llm
    max_iterations: int = 5,
    new_image_uploaded: bool = False,
    user_id: str | None = None,
    regulation_search=None,
    report_scheduler=None,
) -> OrchestratorResult:
    """Run one bounded tool-calling turn and return the assistant answer.

    The user message must already be persisted by the caller before this runs
    so it appears in the loaded history. ``new_image_uploaded`` tells the
    context builder that an image arrived this turn so the Agent is instructed
    to analyze it (the model cannot see images directly).

    ``user_id`` (v0.2) 启用第二层偏好记忆与按用户隔离的历史查询。
    ``regulation_search`` / ``report_scheduler`` 是路由层注入的业务工具回调；
    为 None 时对应工具优雅降级（返回 available=False）。
    """
    # 1. Build system prompt string + history messages (no SystemMessages in list).
    ctx = build_context(
        conn,
        conversation_id,
        user_message,
        new_image_uploaded=new_image_uploaded,
        user_id=user_id,
    )

    # 2. Bind per-request context to the seven domain tools.
    tools = make_tools(
        conn=conn,
        conversation_id=conversation_id,
        user_id=user_id,
        vlm_client=vlm_client,
        vlm_model=vlm_model,
        regulation_search=regulation_search,
        report_scheduler=report_scheduler,
    )

    # 3. Build the LLM and audit callback.
    llm = make_agent_llm(settings)
    audit = AuditCallbackHandler(conn, conversation_id)

    # 4. Create the react agent; system prompt goes via state_modifier so it is
    #    always the leading system message and never appears mid-list.
    agent_executor = create_react_agent(llm, tools, state_modifier=ctx.system_prompt)

    # Each tool call occupies 2 graph steps (invoke + return), plus 1 for the
    # final answer step.
    recursion_limit = max_iterations * 2 + 1
    config = {"callbacks": [audit], "recursion_limit": recursion_limit}

    # 5. Invoke the agent with history-only messages (Human/AIMessage, no System).
    try:
        result = agent_executor.invoke({"messages": ctx.messages}, config=config)
    except GraphRecursionError:
        answer = "抱歉，处理这个请求时步骤过多，已停止。请尝试更具体的提问。"
        repo.add_message(conn, conversation_id, "assistant", answer)
        repo.save_model_response(
            conn, conversation_id, model_role="agent", status="error",
            error=f"exceeded recursion_limit ({recursion_limit})",
        )
        return OrchestratorResult(
            answer=answer, analysis=None, tool_calls=audit.tool_summaries
        )
    except Exception as exc:  # noqa: BLE001
        answer = "抱歉，调用模型时出现错误，请稍后重试。"
        repo.add_message(conn, conversation_id, "assistant", answer)
        repo.save_model_response(
            conn, conversation_id, model_role="agent", status="error", error=str(exc)
        )
        return OrchestratorResult(
            answer=answer, analysis=None, tool_calls=audit.tool_summaries
        )

    # 6. Extract the final answer from the last message.
    final = result["messages"][-1]
    answer = final.content if isinstance(final.content, str) else str(final.content)
    if not answer:
        answer = "(模型未返回文本)"

    # 7. Persist the assistant turn.
    repo.add_message(conn, conversation_id, "assistant", answer)

    # 8. Fetch the latest analysis (may have been written by analyze_image tool).
    raw_analysis = repo.get_latest_analysis(conn, conversation_id)
    analysis = AnalysisResult.model_validate(raw_analysis) if raw_analysis else None

    return OrchestratorResult(
        answer=answer, analysis=analysis, tool_calls=audit.tool_summaries
    )

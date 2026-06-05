"""Conversation context assembly for the Agent orchestrator (U7).

Loads recent messages, the latest analysis result, and latest image metadata
from the repositories and shapes them into the inputs the orchestrator needs:
a Responses API input message list and a populated ToolContext.

Kept separate from orchestration so the loop logic stays small and testable.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.agent.prompts import AGENT_SYSTEM_PROMPT
from app.agent.tools import ToolContext
from app.db import repositories as repo
from app.models.schemas import AnalysisResult
from app.services.responses_client import ResponsesClient

# How many recent messages to include as conversation history.
_HISTORY_LIMIT = 20


@dataclass
class LoadedContext:
    """Assembled context for one agent turn."""

    input_items: list[dict]
    tool_context: ToolContext
    analysis: AnalysisResult | None


def build_context(
    conn: sqlite3.Connection,
    conversation_id: str,
    user_message: str,
    vlm_client: ResponsesClient,
    vlm_model: str,
) -> LoadedContext:
    """Assemble the agent input and tool context for the current turn.

    The current ``user_message`` is expected to already be persisted by the
    caller; it is included from the loaded history.
    """
    # Latest stored analysis (if any) so follow-up tools have something to read.
    raw_analysis = repo.get_latest_analysis(conn, conversation_id)
    analysis = AnalysisResult.model_validate(raw_analysis) if raw_analysis else None

    # Latest uploaded image so analyze_image can run on this turn.
    image_row = repo.get_latest_image(conn, conversation_id)
    image_path = image_row["stored_path"] if image_row else None
    image_mime = image_row["mime_type"] if image_row else None

    # Build the input message list: system prompt + recent history.
    input_items: list[dict] = [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT}
    ]
    messages = repo.list_messages(conn, conversation_id)
    for m in messages[-_HISTORY_LIMIT:]:
        # Responses API accepts simple role/content text messages.
        input_items.append({"role": m["role"], "content": m["content"]})

    tool_context = ToolContext(
        analysis=analysis,
        image_path=image_path,
        image_mime=image_mime,
        vlm_client=vlm_client,
        vlm_model=vlm_model,
        user_question=user_message,
    )

    return LoadedContext(
        input_items=input_items, tool_context=tool_context, analysis=analysis
    )

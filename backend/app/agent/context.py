"""Conversation context assembly for the Agent orchestrator (v0.2 / LangGraph).

Loads recent messages and user preferences from the repositories and assembles:
  - A system prompt string (for create_react_agent's state_modifier parameter).
  - A list of Human/AIMessage objects (conversation history only).

Keeping system content out of the messages list avoids passing SystemMessages
in non-leading positions, which many LLM providers reject.

Kept separate from orchestration so the loop logic stays small and testable.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.agent.prompts import AGENT_SYSTEM_PROMPT
from app.db import repositories as repo

# How many recent messages to include as conversation history.
_HISTORY_LIMIT = 20
# 单条历史消息的字符上限，超出截断（避免超长分析结果挤占上下文）。
_MESSAGE_CHAR_LIMIT = 500


@dataclass
class AgentContext:
    """Result of build_context: system string + history messages."""
    system_prompt: str
    messages: list[BaseMessage] = field(default_factory=list)


def _shape_history(messages: list) -> list[dict]:
    """按方案修剪历史：超过窗口时保留最早一条（首次分析）+ 最近 N-1 条；
    单条超长则截断并加 [已截断] 标记。"""
    if len(messages) > _HISTORY_LIMIT:
        kept = [messages[0]] + list(messages[-(_HISTORY_LIMIT - 1):])
    else:
        kept = list(messages)

    shaped: list[dict] = []
    for m in kept:
        content = m["content"]
        if len(content) > _MESSAGE_CHAR_LIMIT:
            content = content[:_MESSAGE_CHAR_LIMIT] + " …[已截断]"
        shaped.append({"role": m["role"], "content": content})
    return shaped


def build_context(
    conn: sqlite3.Connection,
    conversation_id: str,
    user_message: str,
    new_image_uploaded: bool = False,
    user_id: str | None = None,
) -> AgentContext:
    """Assemble the agent context for the current turn.

    The current ``user_message`` is expected to already be persisted by the
    caller; it is included from the loaded history.

    ``new_image_uploaded`` signals that an image was uploaded on THIS turn. The
    agent model otherwise only sees text messages and has no way to know an
    image is available, so when set we append an explicit instruction to the
    system prompt to call ``analyze_image``.

    ``user_id`` (v0.2) 启用第二层偏好记忆注入与业务工具（query_history）的用户隔离。
    为 None 时退化为 v0.1 行为，保持向后兼容。

    Returns an AgentContext where:
      - system_prompt is a single string for create_react_agent's state_modifier.
      - messages contains only HumanMessage / AIMessage objects (no SystemMessages).
    """
    system_parts = [AGENT_SYSTEM_PROMPT]

    # 第二层记忆：注入该用户的偏好摘要（≤100字），帮助 Agent 个性化回答。
    if user_id is not None:
        prefs = repo.get_preferences(conn, user_id)
        if prefs and prefs.get("preference_summary"):
            system_parts.append(
                f"已知该用户的关注偏好：{prefs['preference_summary']}"
            )

    # The model can't see images directly — tell it one is ready to analyze.
    if new_image_uploaded:
        image_row = repo.get_latest_image(conn, conversation_id)
        if image_row:
            system_parts.append(
                "用户在本轮上传了一张新的施工现场照片，尚未分析。"
                "请先调用 analyze_image 工具对其进行隐患分析，再回答用户的问题。"
            )

    system_prompt = "\n\n".join(system_parts)

    # Convert stored history rows to LangChain message objects (no SystemMessages).
    history: list[BaseMessage] = []
    raw_messages = repo.list_messages(conn, conversation_id)
    for item in _shape_history(raw_messages):
        role = item["role"]
        content = item["content"]
        if role == "assistant":
            history.append(AIMessage(content=content))
        else:
            # "user" and any unexpected roles go to HumanMessage.
            history.append(HumanMessage(content=content))

    return AgentContext(system_prompt=system_prompt, messages=history)

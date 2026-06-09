"""Factory for the LangChain ChatOpenAI instance used by the agent.

The "agent-model" tag lets AuditCallbackHandler distinguish agent LLM calls
from VLM calls, which go through ResponsesClient directly.
"""

from __future__ import annotations

from langchain_openai import ChatOpenAI

from app.core.config import Settings


def make_agent_llm(settings: Settings) -> ChatOpenAI:
    """Return a ChatOpenAI instance configured for the agent model."""
    return ChatOpenAI(
        base_url=settings.openai_api_base_url,
        api_key=settings.openai_api_key,
        model=settings.agent_model,
        temperature=0,
        tags=["agent-model"],
    )

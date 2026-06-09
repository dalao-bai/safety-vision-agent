"""Thin wrapper around the OpenAI-compatible Responses API (U5).

All provider-specific request assembly and response traversal lives here so the
rest of the app depends on a small, stable surface. If a future provider needs
raw HTTP or adapter behavior, isolate it inside this module.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

from openai import OpenAI


@dataclass
class ResponsesResult:
    """Normalized result from a Responses API call."""

    text: str
    provider_id: str | None
    raw: Any


def image_data_url(image_bytes: bytes, mime_type: str) -> str:
    """Encode image bytes as a base64 data URL for Responses image input."""
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime_type};base64,{b64}"


class ResponsesClient:
    """Small client abstraction over the official OpenAI SDK Responses API.

    Tests substitute a fake by passing a client with a compatible
    ``responses.create`` method, so no network access is required.
    """

    def __init__(self, base_url: str, api_key: str, sdk_client: Any | None = None):
        self._client = sdk_client or OpenAI(base_url=base_url, api_key=api_key)

    def create(
        self,
        model: str,
        input_items: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        text_format: dict[str, Any] | None = None,
    ) -> ResponsesResult:
        """Call the Responses API and normalize the result.

        ``input_items`` follows the Responses API input message shape.
        ``text_format`` carries structured-output configuration when supported.
        """
        kwargs: dict[str, Any] = {"model": model, "input": input_items}
        if tools:
            kwargs["tools"] = tools
        if text_format:
            kwargs["text"] = {"format": text_format}

        response = self._client.responses.create(**kwargs)
        return self._normalize(response)

    @staticmethod
    def _normalize(response: Any) -> ResponsesResult:
        """Extract output text and provider id from a Responses API response.

        Prefers the SDK convenience ``output_text``; falls back to traversing
        output content blocks for providers/SDK shapes that lack it.
        """
        provider_id = getattr(response, "id", None)

        text = getattr(response, "output_text", None)
        if text:
            return ResponsesResult(text=text, provider_id=provider_id, raw=response)

        # Fallback: walk output -> content -> text.
        parts: list[str] = []
        for item in getattr(response, "output", []) or []:
            for block in getattr(item, "content", []) or []:
                block_text = getattr(block, "text", None)
                if block_text:
                    parts.append(block_text)
        return ResponsesResult(
            text="".join(parts), provider_id=provider_id, raw=response
        )

    def raw_create(self, **kwargs: Any) -> Any:
        """Escape hatch for the orchestrator's tool-calling loop, which needs the
        full raw response (tool calls, not just text)."""
        return self._client.responses.create(**kwargs)

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts via the OpenAI-compatible embeddings endpoint.

        Reuses the same base_url/api_key as the chat models (v0.2 regulation
        semantic search). Returns one vector per input text, order preserved.
        Tests substitute a fake client exposing ``embeddings.create``.
        """
        response = self._client.embeddings.create(model=model, input=texts)
        # SDK shape: response.data is a list of objects with .embedding; tolerate
        # a plain-dict shape for fakes/tests.
        data = response.get("data") if isinstance(response, dict) else response.data
        vectors: list[list[float]] = []
        for item in data:
            emb = item.get("embedding") if isinstance(item, dict) else item.embedding
            vectors.append(list(emb))
        return vectors

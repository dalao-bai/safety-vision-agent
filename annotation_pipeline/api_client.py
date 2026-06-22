from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .image_utils import image_to_data_url

_MAX_RETRIES = 4
_RETRY_BASE = 2.0  # seconds, doubled each attempt


def call_api(endpoint: str, api_key: str, model: str, prompt: str, image_path: Path, timeout: int) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "instructions": "你是施工现场四口五临边安全隐患识别与预标注助手。只根据图片可见内容输出结构化 JSON。",
        "stream": False,
        "max_tokens": 4096,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": image_to_data_url(image_path)},
                ],
            }
        ],
        "text": {"format": {"type": "json_object"}},
    }
    return post_json(endpoint, api_key, payload, timeout)


def post_json(endpoint: str, api_key: str, payload: dict[str, Any], timeout: int, _attempt: int = 0) -> dict[str, Any]:
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return parse_response_body(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if "response_format" in body:
            payload.pop("response_format", None)
            return post_json(endpoint, api_key, payload, timeout, _attempt)
        # retry on 429 (rate limit) and 5xx (server errors)
        if exc.code in (429, 500, 502, 503, 504) and _attempt < _MAX_RETRIES:
            wait = _RETRY_BASE * (2 ** _attempt)
            print(f"  [retry {_attempt + 1}/{_MAX_RETRIES}] HTTP {exc.code}, retrying in {wait:.0f}s...", flush=True)
            time.sleep(wait)
            return post_json(endpoint, api_key, payload, timeout, _attempt + 1)
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
    except OSError as exc:
        # covers timeout (socket.timeout), connection reset, DNS failure, etc.
        if _attempt < _MAX_RETRIES:
            wait = _RETRY_BASE * (2 ** _attempt)
            print(f"  [retry {_attempt + 1}/{_MAX_RETRIES}] {type(exc).__name__}: {exc}, retrying in {wait:.0f}s...", flush=True)
            time.sleep(wait)
            return post_json(endpoint, api_key, payload, timeout, _attempt + 1)
        raise


def parse_response_body(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("data:"):
        return parse_sse_response(stripped)
    return json.loads(stripped)


def parse_sse_response(text: str) -> dict[str, Any]:
    chunks: list[dict[str, Any]] = []
    content_parts: list[str] = []
    final_usage: Any = None
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            continue
        chunks.append(chunk)
        if chunk.get("usage"):
            final_usage = chunk["usage"]
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            message = choice.get("message") or {}
            for content in (delta.get("content"), message.get("content"), choice.get("text")):
                if isinstance(content, str):
                    content_parts.append(content)
                elif isinstance(content, list):
                    content_parts.extend(part.get("text", "") for part in content if isinstance(part, dict))
    content = "".join(content_parts)
    if not content:
        raise ValueError(f"SSE response contained no completion content: {text[:500]}")
    first = chunks[0] if chunks else {}
    return {
        "id": first.get("id", ""),
        "object": "chat.completion",
        "created": first.get("created", 0),
        "model": first.get("model", ""),
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": final_usage,
    }


def extract_response_text(response: dict[str, Any]) -> str:
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    output = response.get("output")
    if isinstance(output, list):
        parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            for content in item.get("content") or []:
                if not isinstance(content, dict):
                    continue
                if isinstance(content.get("text"), str):
                    parts.append(content["text"])
                elif isinstance(content.get("output_text"), str):
                    parts.append(content["output_text"])
        if parts:
            return "".join(parts)
    choices = response.get("choices") or []
    if not choices:
        raise ValueError("API response has no choices")
    content = (choices[0].get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    raise ValueError("API response content is not text")


def parse_json_text(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.S)
        if not match:
            raise
        return json.loads(match.group(0))

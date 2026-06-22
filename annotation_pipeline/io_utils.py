from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_config(path: Path) -> dict[str, Any]:
    return load_json(path)


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")


def append_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def chat_endpoint(endpoint: str) -> str:
    clean_endpoint = endpoint.rstrip("/")
    if clean_endpoint.endswith("/chat/completions"):
        return clean_endpoint
    if clean_endpoint.endswith("/images/generations"):
        return clean_endpoint[: -len("/images/generations")] + "/chat/completions"
    if clean_endpoint.endswith("/v1"):
        return clean_endpoint + "/chat/completions"
    return endpoint


def responses_endpoint(endpoint: str) -> str:
    clean_endpoint = endpoint.rstrip("/")
    if clean_endpoint.endswith("/responses"):
        return clean_endpoint
    if clean_endpoint.endswith("/chat/completions"):
        return clean_endpoint[: -len("/chat/completions")] + "/responses"
    if clean_endpoint.endswith("/images/generations"):
        return clean_endpoint[: -len("/images/generations")] + "/responses"
    if clean_endpoint.endswith("/v1"):
        return clean_endpoint + "/responses"
    return endpoint

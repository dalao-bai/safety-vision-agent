"""Tests for the VLM image analyzer (U5).

Uses a fake ResponsesClient so no network access is required. Verifies the
success path, error persistence (raw response carried for audit), and the
needs-followup edge case.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.services.responses_client import ResponsesResult
from app.services.vlm_analyzer import analyze_image


class _FakeClient:
    """Stands in for ResponsesClient.create. Either returns a ResponsesResult
    or raises to simulate an API failure."""

    def __init__(self, *, text: str | None = None, raise_exc: Exception | None = None):
        self._text = text
        self._raise = raise_exc
        self.last_input: list[dict[str, Any]] | None = None
        self.last_text_format: dict[str, Any] | None = None
        self.last_model: str | None = None

    def create(self, model, input_items, tools=None, text_format=None):
        self.last_model = model
        self.last_input = input_items
        self.last_text_format = text_format
        if self._raise is not None:
            raise self._raise
        return ResponsesResult(text=self._text, provider_id="resp_x", raw=None)


@pytest.fixture
def image_file(tmp_path):
    p = tmp_path / "site.jpg"
    p.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg-bytes")
    return str(p)


_VALID_JSON = json.dumps(
    {
        "summary": "存在高空作业隐患",
        "hazards": [
            {
                "name": "未系安全带",
                "location": "脚手架顶部",
                "risk_level": "high",
                "basis": "工人在高处无防护",
                "remediation": "立即佩戴安全带",
                "confidence": 0.9,
            }
        ],
        "needs_followup": False,
        "followup_question": None,
    },
    ensure_ascii=False,
)


def test_valid_json_produces_analysis_result(image_file):
    client = _FakeClient(text=_VALID_JSON)
    outcome = analyze_image(client, "vlm-model", image_file, "image/jpeg")

    assert outcome.ok is True
    assert outcome.result is not None
    assert outcome.result.summary == "存在高空作业隐患"
    assert outcome.result.hazards[0].name == "未系安全带"
    assert outcome.error is None
    assert outcome.provider_id == "resp_x"


def test_request_includes_image_and_configured_model(image_file):
    client = _FakeClient(text=_VALID_JSON)
    analyze_image(client, "vlm-model", image_file, "image/jpeg")

    assert client.last_model == "vlm-model"
    # The user content must include an image input block.
    user_msg = next(m for m in client.last_input if m["role"] == "user")
    content_types = {block["type"] for block in user_msg["content"]}
    assert "input_image" in content_types
    assert "input_text" in content_types


def test_request_includes_structured_output_schema(image_file):
    client = _FakeClient(text=_VALID_JSON)
    analyze_image(client, "vlm-model", image_file, "image/jpeg")

    assert client.last_text_format is not None
    assert client.last_text_format["type"] == "json_schema"


def test_api_failure_returns_typed_error(image_file):
    client = _FakeClient(raise_exc=RuntimeError("connection refused"))
    outcome = analyze_image(client, "vlm-model", image_file, "image/jpeg")

    assert outcome.ok is False
    assert outcome.result is None
    assert "connection refused" in outcome.error


def test_natural_language_output_fails_and_records_raw(image_file):
    client = _FakeClient(text="这张照片里有一些安全问题，但我不确定。")
    outcome = analyze_image(client, "vlm-model", image_file, "image/jpeg")

    assert outcome.ok is False
    assert outcome.result is None
    assert outcome.raw_text == "这张照片里有一些安全问题，但我不确定。"
    assert "not valid json" in outcome.error.lower()


def test_json_missing_required_field_fails_validation(image_file):
    bad = json.dumps({"summary": "x", "hazards": [{"name": "缺字段"}]})
    client = _FakeClient(text=bad)
    outcome = analyze_image(client, "vlm-model", image_file, "image/jpeg")

    assert outcome.ok is False
    assert outcome.raw_text == bad
    assert "schema validation" in outcome.error.lower()


def test_no_hazards_with_followup_accepted(image_file):
    raw = json.dumps(
        {
            "summary": "图像不清晰",
            "hazards": [],
            "needs_followup": True,
            "followup_question": "能否提供更清晰的照片?",
        },
        ensure_ascii=False,
    )
    client = _FakeClient(text=raw)
    outcome = analyze_image(client, "vlm-model", image_file, "image/jpeg")

    assert outcome.ok is True
    assert outcome.result.needs_followup is True
    assert outcome.result.followup_question == "能否提供更清晰的照片?"


def test_unreadable_image_returns_error(tmp_path):
    client = _FakeClient(text=_VALID_JSON)
    missing = str(tmp_path / "does-not-exist.jpg")
    outcome = analyze_image(client, "vlm-model", missing, "image/jpeg")

    assert outcome.ok is False
    assert "failed to read image" in outcome.error.lower()

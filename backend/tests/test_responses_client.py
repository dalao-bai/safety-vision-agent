"""Tests for the Responses API client wrapper (U5).

Uses a fake SDK client so no network access is required. Verifies request
assembly at the client boundary and response normalization.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.services.responses_client import ResponsesClient, image_data_url


class _FakeResponses:
    def __init__(self, response: Any):
        self._response = response
        self.last_kwargs: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> Any:
        self.last_kwargs = kwargs
        return self._response


class _FakeSDK:
    def __init__(self, response: Any):
        self.responses = _FakeResponses(response)


def test_image_data_url_encodes_base64():
    url = image_data_url(b"hello", "image/jpeg")
    assert url.startswith("data:image/jpeg;base64,")
    # "hello" base64 == aGVsbG8=
    assert url.endswith("aGVsbG8=")


def test_create_passes_model_and_input():
    fake = _FakeSDK(SimpleNamespace(id="resp_1", output_text="hi"))
    client = ResponsesClient("http://x", "key", sdk_client=fake)

    result = client.create(model="m1", input_items=[{"role": "user", "content": "q"}])

    assert fake.responses.last_kwargs["model"] == "m1"
    assert fake.responses.last_kwargs["input"] == [{"role": "user", "content": "q"}]
    assert result.text == "hi"
    assert result.provider_id == "resp_1"


def test_create_includes_tools_and_text_format_when_given():
    fake = _FakeSDK(SimpleNamespace(id="resp_2", output_text="{}"))
    client = ResponsesClient("http://x", "key", sdk_client=fake)

    tools = [{"type": "function", "name": "analyze_image"}]
    text_format = {"type": "json_schema", "name": "x", "schema": {}}
    client.create(
        model="m", input_items=[], tools=tools, text_format=text_format
    )

    assert fake.responses.last_kwargs["tools"] == tools
    assert fake.responses.last_kwargs["text"] == {"format": text_format}


def test_normalize_falls_back_to_output_content_blocks():
    # No output_text; must walk output -> content -> text.
    response = SimpleNamespace(
        id="resp_3",
        output_text=None,
        output=[
            SimpleNamespace(
                content=[
                    SimpleNamespace(text="part1"),
                    SimpleNamespace(text="part2"),
                ]
            )
        ],
    )
    fake = _FakeSDK(response)
    client = ResponsesClient("http://x", "key", sdk_client=fake)

    result = client.create(model="m", input_items=[])
    assert result.text == "part1part2"
    assert result.provider_id == "resp_3"

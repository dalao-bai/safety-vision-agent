"""VLM image analyzer (U5).

Reads a stored image, sends it to the configured VLM via the Responses API
requesting structured hazard JSON, validates the result against the domain
schema, and returns a typed outcome. Raw responses and errors are returned to
the caller for persistence (the orchestrator/tool layer owns the DB).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from app.agent.prompts import HAZARD_JSON_SCHEMA, VLM_SYSTEM_PROMPT
from app.models.schemas import AnalysisResult
from app.services.responses_client import ResponsesClient, image_data_url


@dataclass
class AnalyzerOutcome:
    """Result of a VLM analysis attempt.

    Exactly one of ``result`` (success) or ``error`` (failure) is meaningful.
    ``raw_text`` and ``provider_id`` are always carried for audit persistence.
    """

    ok: bool
    result: AnalysisResult | None
    raw_text: str | None
    provider_id: str | None
    error: str | None


# Structured-output format for the Responses API. Providers that support JSON
# Schema will enforce this; the analyzer still validates server-side regardless.
_TEXT_FORMAT = {
    "type": "json_schema",
    "name": "hazard_analysis",
    "schema": HAZARD_JSON_SCHEMA,
    "strict": True,
}


def analyze_image(
    client: ResponsesClient,
    model: str,
    image_path: str,
    mime_type: str,
    question: str | None = None,
) -> AnalyzerOutcome:
    """Analyze one image and return a typed outcome.

    On any failure (API error, non-JSON output, schema violation) the raw
    response (when available) is preserved and ``ok`` is False.
    """
    try:
        image_bytes = Path(image_path).read_bytes()
    except OSError as exc:
        return AnalyzerOutcome(
            ok=False, result=None, raw_text=None, provider_id=None,
            error=f"failed to read image: {exc}",
        )

    data_url = image_data_url(image_bytes, mime_type)
    user_text = question or "请识别这张施工现场照片中的安全隐患。"

    input_items = [
        {"role": "system", "content": VLM_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": user_text},
                {"type": "input_image", "image_url": data_url},
            ],
        },
    ]

    try:
        response = client.create(
            model=model,
            input_items=input_items,
            text_format=_TEXT_FORMAT,
        )
    except Exception as exc:  # noqa: BLE001 - surface any provider/SDK error as audit data
        return AnalyzerOutcome(
            ok=False, result=None, raw_text=None, provider_id=None,
            error=f"VLM API call failed: {exc}",
        )

    raw_text = response.text
    provider_id = response.provider_id

    # Parse JSON.
    try:
        parsed = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        return AnalyzerOutcome(
            ok=False, result=None, raw_text=raw_text, provider_id=provider_id,
            error="VLM output was not valid JSON",
        )

    # Validate against the hazard schema.
    try:
        result = AnalysisResult.model_validate(parsed)
    except ValidationError as exc:
        return AnalyzerOutcome(
            ok=False, result=None, raw_text=raw_text, provider_id=provider_id,
            error=f"VLM output failed schema validation: {exc}",
        )

    return AnalyzerOutcome(
        ok=True, result=result, raw_text=raw_text, provider_id=provider_id, error=None
    )

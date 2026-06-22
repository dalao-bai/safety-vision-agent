from __future__ import annotations

import base64
import json
import mimetypes
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.kg.store import KGStore

_VLM_INSTRUCTION = (
    "你是四口五临边安全隐患识别模型。仔细看图,输出整图结论与隐患列表的 JSON。"
)


class DetectionError(Exception):
    pass


@dataclass
class Hazard:
    object_id: str
    object_name: str
    status: str
    hazard_type_id: str | None
    hazard_type: str | None
    bbox: list[int] | None
    visual_evidence: str
    rule_basis: str
    evidence_sufficiency: str
    uncertainty_reason: str | None
    reasoning_chain: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DetectionResult:
    scene: str
    hazards: list[Hazard]


def _image_data_url(path: str) -> str:
    p = Path(path)
    mime = mimetypes.guess_type(p.name)[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode("ascii")


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n```$", "", text)
    return text.strip()


def _extract_hazards(parsed: Any) -> tuple[str, list[dict]]:
    if isinstance(parsed, list):
        return "four_openings_edges", parsed
    if isinstance(parsed, dict):
        scene = parsed.get("scene") or "four_openings_edges"
        for key in ("hazards", "objects", "results"):
            if isinstance(parsed.get(key), list):
                return scene, parsed[key]
        if "status" in parsed or "related_object" in parsed:
            return scene, [parsed]
    raise DetectionError(f"unrecognized VLM output shape: {type(parsed).__name__}")


class Detector:
    def __init__(self, client: Any, model: str, kg: KGStore):
        self._client = client
        self._model = model
        self._kg = kg

    def detect(self, image_path: str) -> DetectionResult:
        content = self._call(image_path)
        try:
            parsed = json.loads(_strip_fences(content))
        except json.JSONDecodeError as exc:
            raise DetectionError(f"VLM output is not valid JSON: {exc}") from exc
        scene, raw_hazards = _extract_hazards(parsed)
        return DetectionResult(scene=scene, hazards=[self._to_hazard(h) for h in raw_hazards])

    def _call(self, image_path: str) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": _VLM_INSTRUCTION},
                    {"type": "image_url", "image_url": {"url": _image_data_url(image_path)}},
                ],
            }],
            temperature=0,
        )
        return resp.choices[0].message.content or ""

    def _to_hazard(self, raw: dict) -> Hazard:
        object_id = raw.get("object_id") or ""
        object_name = raw.get("object_name") or raw.get("related_object") or ""
        if not object_id and object_name:
            object_id = self._kg.object_id_for_name(object_name) or ""
        if object_id and not object_name:
            obj = self._kg.get_object(object_id)
            object_name = obj["name"] if obj else ""
        bbox = raw.get("bbox") or raw.get("object_bbox")
        return Hazard(
            object_id=object_id,
            object_name=object_name,
            status=raw.get("status", ""),
            hazard_type_id=raw.get("hazard_type_id"),
            hazard_type=raw.get("hazard_type"),
            bbox=[int(round(float(v))) for v in bbox] if isinstance(bbox, list) and len(bbox) == 4 else None,
            visual_evidence=raw.get("visual_evidence", ""),
            rule_basis=raw.get("rule_basis", ""),
            evidence_sufficiency=raw.get("evidence_sufficiency", ""),
            uncertainty_reason=raw.get("uncertainty_reason"),
            reasoning_chain=raw.get("reasoning_chain", []) or [],
        )


def build_detector(settings, kg: KGStore) -> Detector:
    from openai import OpenAI
    client = OpenAI(base_url=settings.vlm_api_base_url, api_key=settings.vlm_api_key)
    return Detector(client=client, model=settings.vlm_model, kg=kg)

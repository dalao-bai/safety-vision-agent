from __future__ import annotations

import base64
import json
import mimetypes
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.kg.store import KGStore

# 完整格式：微调模型就绪后启用（含 rule_basis / evidence_sufficiency / reasoning_chain 等飞轮字段）
_VLM_INSTRUCTION_FULL = (
    "你是四口五临边安全隐患识别模型。仔细看图,输出整图结论与隐患列表的 JSON。"
)

# 简化格式：先跑通用，微调数据只需输出这几个字段
# {
#   "scene": "四口五临边",
#   "hazards": [
#     {
#       "related_object": "基坑临边防护",
#       "hazard_type_id": "missing_protection",   // 无法判断时填 null
#       "status": "confirmed_hazard",              // confirmed_hazard | uncertain | safe
#       "visual_evidence": "坑边无防护栏杆",
#       "object_bbox": [x1, y1, x2, y2]           // 可省略
#     }
#   ]
# }
_VLM_INSTRUCTION_SIMPLE = """\
你是四口五临边安全隐患识别模型。仔细看图，以 JSON 输出隐患列表，格式如下：
{"scene":"四口五临边","hazards":[{"related_object":"<防护对象名称>","hazard_type_id":"<隐患类型id或null>","status":"confirmed_hazard|uncertain|safe","visual_evidence":"<一句话视觉依据>","object_bbox":[x1,y1,x2,y2]}]}
related_object 必须从以下 9 个名称中选一个，不得自行创造：楼梯口防护、电梯井口防护、预留洞口防护、通道口防护、阳台临边防护、屋面临边防护、楼层临边防护、基坑临边防护、跑道（斜道）临边防护。
hazard_type_id 取值：missing_protection / discontinuous_protection / temporary_substitute / unstable_fixation / missing_protective_door / passage_abnormal，无法判断填 null。
只输出 JSON，不要其他文字。\
"""

_VLM_INSTRUCTION = _VLM_INSTRUCTION_FULL  # 向后兼容，外部若有直接引用不受影响


class DetectionError(Exception):
    pass


@dataclass
class Hazard:
    """图像中识别到的单条隐患记录。"""

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
    missing_evidence: str | None = None


@dataclass
class DetectionResult:
    """单张图像的VLM输出：场景标签与隐患列表。"""

    scene: str
    hazards: list[Hazard]


def _image_data_url(path: str) -> str:
    p = Path(path)
    mime = mimetypes.guess_type(p.name)[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode("ascii")


def _strip_fences(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```[a-zA-Z]*\r?\n(.*?)(?:\r?\n```.*)?$", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text


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
    """调用VLM并将JSON输出解析为DetectionResult。"""

    def __init__(self, client: Any, model: str, kg: KGStore,
                 instruction: str = _VLM_INSTRUCTION_SIMPLE):
        self._client = client
        self._model = model
        self._kg = kg
        self._instruction = instruction

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
                    {"type": "text", "text": self._instruction},
                    {"type": "image_url", "image_url": {"url": _image_data_url(image_path)}},
                ],
            }],
            temperature=0,
        )
        return resp.choices[0].message.content or ""

    def _to_hazard(self, raw: dict) -> Hazard:
        if not isinstance(raw, dict):
            raise DetectionError(f"hazard element is not a dict: {type(raw).__name__}")
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
            missing_evidence=raw.get("missing_evidence"),
        )


def build_detector(settings, kg: KGStore) -> Detector:
    from openai import OpenAI
    client = OpenAI(base_url=settings.vlm_api_base_url, api_key=settings.vlm_api_key)
    instruction = _VLM_INSTRUCTION_FULL if settings.vlm_instruction_mode == "full" else _VLM_INSTRUCTION_SIMPLE
    return Detector(client=client, model=settings.vlm_model, kg=kg, instruction=instruction)

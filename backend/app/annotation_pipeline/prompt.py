from __future__ import annotations

from pathlib import Path

from .constants import HAZARD_TYPES, OBJECT_TYPES, UNCERTAINTY_REASONS
from .rules import RuleStore


def build_prompt(image_path: Path, width: int, height: int, rules: RuleStore) -> str:
    objects = "\n".join(f"- {oid}: {name}" for oid, name in OBJECT_TYPES)
    hazards = "\n".join(f"- {hid}: {name}" for hid, name in HAZARD_TYPES)
    uncertainty = "\n".join(f"- {item}" for item in UNCERTAINTY_REASONS)
    return f"""你是施工现场“四口五临边”安全隐患识别助手。只根据图片可见内容判断，不要根据文件名或外部信息推断。

图片尺寸：{width}x{height}

只允许输出以下 object_id：
{objects}

confirmed_hazard 只允许输出以下 hazard_type_id：
{hazards}

uncertain 只能使用以下 uncertainty_reason：
{uncertainty}

判断要求：
1. bbox 使用像素坐标 [x1,y1,x2,y2]，原点在左上角，坐标必须在图片尺寸范围内。
2. status 只能是 confirmed_hazard、safe、uncertain。
3. confirmed_hazard 时 hazard_type_id/hazard_type 必须填写；safe 或 uncertain 时二者必须为 null。
4. visual_evidence 必须描述图片中直接可见的对象、防护构件和异常证据。
5. uncertain 只用于证据不足：关键防护构件不可见或被遮挡；图像不足以判断尺度、强度或固定状态；判断依赖工程阶段、验收记录或现场复核资料。
6. safe 表示对象可见且未见明显异常，不要因为缺少文档就把所有安全对象判为 uncertain。
7. 可以输出多个 objects；没有四口五临边对象则输出空数组。
8. 不要输出 sample_id、image_path、scene、width、height、rule，这些字段由程序补充。

只输出 JSON，不要输出 Markdown。格式：
{{
  "objects": [
    {{
      "object_id": "reserved_opening_protection",
      "object_name": "预留洞口防护",
      "bbox": [0, 0, 100, 100],
      "status": "confirmed_hazard",
      "hazard_type_id": "opening_uncovered",
      "hazard_type": "洞口敞开",
      "visual_evidence": "图中可见楼板洞口裸露，未见盖板或围护。",
      "missing_evidence": null,
      "evidence_sufficiency": "sufficient",
      "uncertainty_reason": null
    }}
  ]
}}"""

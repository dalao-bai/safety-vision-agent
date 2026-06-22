from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .constants import (
    DRAFT_SCHEMA_VERSION,
    HAZARD_ID_BY_NAME,
    HAZARD_NAME_BY_ID,
    OBJECT_ID_BY_NAME,
    OBJECT_NAME_BY_ID,
    UNCERTAINTY_REASONS,
)
from .image_utils import stable_sample_id
from .rules import RuleStore


def normalize_bbox(value: Any, width: int, height: int) -> tuple[list[int] | None, list[str]]:
    warnings: list[str] = []
    if not isinstance(value, list) or len(value) != 4:
        return None, ["missing_or_invalid_bbox"]
    try:
        x1, y1, x2, y2 = [int(round(float(v))) for v in value]
    except Exception:
        return None, ["non_numeric_bbox"]
    original = [x1, y1, x2, y2]
    x1 = max(0, min(width - 1, x1))
    y1 = max(0, min(height - 1, y1))
    x2 = max(0, min(width - 1, x2))
    y2 = max(0, min(height - 1, y2))
    if x2 <= x1 or y2 <= y1:
        return original, ["degenerate_bbox"]
    bbox = [x1, y1, x2, y2]
    if bbox != original:
        warnings.append("bbox_clamped_to_image")
    return bbox, warnings


def normalize_object(raw: dict[str, Any], index: int, width: int, height: int, rules: RuleStore) -> dict[str, Any]:
    warnings: list[str] = []
    object_id = raw.get("object_id")
    object_name = raw.get("object_name")
    if object_id not in OBJECT_NAME_BY_ID and object_name in OBJECT_ID_BY_NAME:
        object_id = OBJECT_ID_BY_NAME[object_name]
    if object_id not in OBJECT_NAME_BY_ID:
        warnings.append("unknown_object_id")
    normalized_name = OBJECT_NAME_BY_ID.get(object_id, object_name or "")
    if object_name and object_name != normalized_name:
        warnings.append("object_name_normalized_from_object_id")

    status = raw.get("status")
    if status not in {"confirmed_hazard", "safe", "uncertain"}:
        warnings.append("unknown_status")

    hazard_type_id = raw.get("hazard_type_id")
    hazard_type = raw.get("hazard_type")
    if status == "confirmed_hazard":
        if hazard_type_id not in HAZARD_NAME_BY_ID and hazard_type in HAZARD_ID_BY_NAME:
            hazard_type_id = HAZARD_ID_BY_NAME[hazard_type]
        hazard_type = HAZARD_NAME_BY_ID.get(hazard_type_id, hazard_type)
        if hazard_type_id not in HAZARD_NAME_BY_ID:
            warnings.append("missing_or_unknown_hazard_type_id")
    else:
        hazard_type_id = None
        hazard_type = None

    bbox, bbox_warnings = normalize_bbox(raw.get("bbox"), width, height)
    warnings.extend(bbox_warnings)

    evidence_sufficiency = raw.get("evidence_sufficiency")
    if status == "uncertain":
        evidence_sufficiency = "insufficient"
    elif status in {"confirmed_hazard", "safe"}:
        evidence_sufficiency = "sufficient"
    elif evidence_sufficiency not in {"sufficient", "insufficient"}:
        evidence_sufficiency = "insufficient"

    uncertainty_reason = raw.get("uncertainty_reason")
    missing_evidence = raw.get("missing_evidence")
    if status == "uncertain":
        if uncertainty_reason not in UNCERTAINTY_REASONS:
            warnings.append("missing_or_unknown_uncertainty_reason")
        if not isinstance(missing_evidence, str) or not missing_evidence.strip():
            warnings.append("missing_uncertain_missing_evidence")
    else:
        uncertainty_reason = None
        missing_evidence = None

    visual_evidence = raw.get("visual_evidence")
    if not isinstance(visual_evidence, str) or not visual_evidence.strip():
        visual_evidence = ""
        warnings.append("missing_visual_evidence")

    if status == "safe":
        rule_id, rule = None, ""
    else:
        rule_id, rule, rule_warnings = rules.choose_rule(
            {
                **raw,
                "object_id": object_id,
                "status": status,
                "hazard_type_id": hazard_type_id,
                "visual_evidence": visual_evidence,
            }
        )
        warnings.extend(rule_warnings)
        if not rule:
            warnings.append("missing_rule_text")

    return {
        "draft_object_index": index,
        "object_id": object_id,
        "object_name": normalized_name,
        "bbox": bbox,
        "status": status,
        "hazard_type_id": hazard_type_id,
        "hazard_type": hazard_type,
        "visual_evidence": visual_evidence,
        "missing_evidence": missing_evidence,
        "evidence_sufficiency": evidence_sufficiency,
        "uncertainty_reason": uncertainty_reason,
        "rule_id": rule_id,
        "rule": rule,
        "validation_warnings": sorted(set(warnings)),
    }


def normalize_draft(parsed: dict[str, Any], image_path: Path, width: int, height: int, rules: RuleStore, model: str, mock: bool) -> dict[str, Any]:
    raw_objects = parsed.get("objects") or []
    if not isinstance(raw_objects, list):
        raw_objects = []
    objects = [normalize_object(obj if isinstance(obj, dict) else {}, i, width, height, rules) for i, obj in enumerate(raw_objects, 1)]
    return {
        "schema_version": DRAFT_SCHEMA_VERSION,
        "sample_id": stable_sample_id(image_path),
        "original_sample_id": parsed.get("sample_id") or image_path.stem,
        "image_path": image_path.as_posix(),
        "width": width,
        "height": height,
        "scene": "four_openings_edges",
        "model": model,
        "mock": mock,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "objects": objects,
    }

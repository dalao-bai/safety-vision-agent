from __future__ import annotations

from datetime import datetime
from typing import Any


SCHEMA_VERSION = "foe_annotation_v1.0"
DRAFT_SCHEMA_VERSION = "agent_annotation_draft_v1.0"


def build_draft_from_analysis(sample_id: str, image_path: str, fused_result: dict, vlm_result: dict, yolo_result: dict) -> dict:
    objects = []
    for item in fused_result.get("hazards") or []:
        objects.append(normalize_draft_object(item, len(objects) + 1))
    for item in fused_result.get("uncertain_items") or []:
        objects.append(normalize_draft_object(item, len(objects) + 1))

    return {
        "schema_version": DRAFT_SCHEMA_VERSION,
        "sample_id": sample_id,
        "image_path": image_path,
        "scene": "four_openings_edges",
        "generated_at": datetime.utcnow().isoformat(timespec="seconds"),
        "source": "analysis_result",
        "model_outputs": {
            "vlm": vlm_result,
            "yolo": yolo_result,
        },
        "objects": objects,
    }


def build_review_template(sample_id: str, image_path: str, draft_json: dict, reviewer: str | None, note: str) -> dict:
    return {
        "sample_id": sample_id,
        "image_path": image_path,
        "review_status": "pending",
        "image_decision": "accept",
        "reviewer": reviewer,
        "review_note": note,
        "objects": [
            {
                "draft_object_index": obj.get("draft_object_index", index),
                "decision": "pending",
                "revised": obj,
                "note": "",
            }
            for index, obj in enumerate(draft_json.get("objects") or [], 1)
        ],
    }


def normalize_draft_object(item: dict[str, Any], index: int) -> dict:
    status = item.get("status")
    hazard_type_id = item.get("hazard_type_id") if status == "confirmed_hazard" else None
    hazard_type = item.get("hazard_type") if status == "confirmed_hazard" else None
    return {
        "draft_object_index": index,
        "object_id": item.get("object_id") or "",
        "object_name": item.get("object_name") or "",
        "bbox": item.get("bbox") or [],
        "status": status or "uncertain",
        "hazard_type_id": hazard_type_id,
        "hazard_type": hazard_type,
        "visual_evidence": item.get("visual_evidence") or "",
        "missing_evidence": item.get("missing_evidence"),
        "evidence_sufficiency": item.get("evidence_sufficiency") or ("insufficient" if status == "uncertain" else "sufficient"),
        "uncertainty_reason": item.get("uncertainty_reason") if status == "uncertain" else None,
        "rule": item.get("rule") or "",
        "confidence": item.get("confidence"),
    }


def apply_review_update(current_review: dict, reviewer: str | None, image_decision: str, review_status: str, objects: list[dict], note: str) -> dict:
    by_index = {item["draft_object_index"]: item for item in objects}
    updated_objects = []
    for current in current_review.get("objects") or []:
        draft_index = current.get("draft_object_index")
        incoming = by_index.get(draft_index)
        if incoming:
            updated_objects.append(
                {
                    "draft_object_index": draft_index,
                    "decision": incoming.get("decision", "pending"),
                    "revised": incoming.get("revised") or current.get("revised") or {},
                    "note": incoming.get("note", ""),
                }
            )
        else:
            updated_objects.append(current)

    return {
        **current_review,
        "review_status": review_status,
        "image_decision": image_decision,
        "reviewer": reviewer if reviewer is not None else current_review.get("reviewer"),
        "review_note": note,
        "objects": updated_objects,
    }


def build_accepted_records(sample_id: str, image_path: str, review_json: dict, draft_json: dict) -> dict:
    if review_json.get("image_decision") == "reject":
        return {"images": [], "objects": [], "errors": []}

    draft_by_index = {obj.get("draft_object_index"): obj for obj in draft_json.get("objects") or []}
    accepted_objects = []
    errors = []

    for item in review_json.get("objects") or []:
        decision = item.get("decision")
        if decision in {"pending", "reject"}:
            continue
        if decision == "accept":
            obj = draft_by_index.get(item.get("draft_object_index"))
        elif decision == "revise":
            obj = item.get("revised")
        else:
            errors.append({"object": item.get("draft_object_index"), "error": f"unknown decision: {decision}"})
            continue
        if not isinstance(obj, dict):
            errors.append({"object": item.get("draft_object_index"), "error": "missing object payload"})
            continue
        validation_errors = validate_training_object(obj)
        if validation_errors:
            errors.append({"object": item.get("draft_object_index"), "error": "; ".join(validation_errors)})
            continue
        accepted_objects.append(obj)

    if not accepted_objects:
        return {"images": [], "objects": [], "errors": errors}

    image_record = {
        "schema_version": SCHEMA_VERSION,
        "sample_id": sample_id,
        "image_path": image_path,
        "width": None,
        "height": None,
        "scene": "four_openings_edges",
        "source_type": "agent_human_review",
        "source_id": review_json.get("source_analysis_id"),
        "split_group": None,
        "image_quality": "usable",
        "image_tags": ["agent_feedback"],
        "notes": review_json.get("review_note", ""),
    }
    object_records = []
    for index, obj in enumerate(accepted_objects, 1):
        object_records.append(
            {
                "schema_version": SCHEMA_VERSION,
                "object_instance_id": f"{sample_id}_obj_{index:02d}",
                "sample_id": sample_id,
                "object_id": obj["object_id"],
                "object_name": obj["object_name"],
                "gt_bbox": obj["bbox"],
                "status": obj["status"],
                "hazard_type_id": obj.get("hazard_type_id"),
                "hazard_type": obj.get("hazard_type"),
                "visual_evidence": obj["visual_evidence"],
                "missing_evidence": obj.get("missing_evidence"),
                "evidence_sufficiency": obj["evidence_sufficiency"],
                "uncertainty_reason": obj.get("uncertainty_reason"),
                "rule_id": obj.get("rule_id"),
                "rule": obj["rule"],
                "difficulty_tags": [],
                "annotation_note": "",
            }
        )
    return {"images": [image_record], "objects": object_records, "errors": errors}


def validate_training_object(obj: dict) -> list[str]:
    errors = []
    if not obj.get("object_id"):
        errors.append("object_id is required")
    if not obj.get("object_name"):
        errors.append("object_name is required")
    bbox = obj.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        errors.append("bbox must be [x1,y1,x2,y2]")
    status = obj.get("status")
    if status not in {"confirmed_hazard", "safe", "uncertain"}:
        errors.append("invalid status")
    if status == "confirmed_hazard" and not obj.get("hazard_type_id"):
        errors.append("confirmed_hazard requires hazard_type_id")
    if status == "uncertain":
        if obj.get("evidence_sufficiency") != "insufficient":
            errors.append("uncertain requires insufficient evidence")
        if not obj.get("uncertainty_reason"):
            errors.append("uncertain requires uncertainty_reason")
    if status in {"confirmed_hazard", "safe"} and obj.get("evidence_sufficiency") != "sufficient":
        errors.append("confirmed_hazard/safe requires sufficient evidence")
    if not obj.get("visual_evidence"):
        errors.append("visual_evidence is required")
    if not obj.get("rule"):
        errors.append("rule is required")
    return errors

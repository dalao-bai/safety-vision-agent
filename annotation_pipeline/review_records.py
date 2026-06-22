from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .constants import HAZARD_NAME_BY_ID, OBJECT_NAME_BY_ID, SCHEMA_VERSION, UNCERTAINTY_REASONS
from .io_utils import append_jsonl, load_json, write_json, write_jsonl
from .review_index import REVIEW_ONLY_KEYS, upgrade_review_with_draft


def validate_accepted_object(obj: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if obj.get("object_id") not in OBJECT_NAME_BY_ID:
        errors.append("invalid object_id")
    if obj.get("object_name") != OBJECT_NAME_BY_ID.get(obj.get("object_id")):
        errors.append("object_name does not match object_id")
    bbox = obj.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4 or not all(isinstance(v, int) for v in bbox):
        errors.append("bbox must be four integers")
    elif bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        errors.append("bbox must satisfy x1<x2 and y1<y2")
    status = obj.get("status")
    if status not in {"confirmed_hazard", "safe", "uncertain"}:
        errors.append("invalid status")
    if status == "confirmed_hazard":
        if obj.get("hazard_type_id") not in HAZARD_NAME_BY_ID:
            errors.append("confirmed_hazard requires hazard_type_id")
        if obj.get("evidence_sufficiency") != "sufficient":
            errors.append("confirmed_hazard requires sufficient evidence")
    if status == "safe":
        if obj.get("hazard_type_id") is not None or obj.get("hazard_type") is not None:
            errors.append("safe requires null hazard fields")
        if obj.get("evidence_sufficiency") != "sufficient":
            errors.append("safe requires sufficient evidence")
    if status == "uncertain":
        if obj.get("hazard_type_id") is not None or obj.get("hazard_type") is not None:
            errors.append("uncertain requires null hazard fields")
        if obj.get("evidence_sufficiency") != "insufficient":
            errors.append("uncertain requires insufficient evidence")
        if obj.get("uncertainty_reason") not in UNCERTAINTY_REASONS:
            errors.append("uncertain requires fixed uncertainty_reason")
        if not obj.get("missing_evidence"):
            errors.append("uncertain requires missing_evidence")
    if not obj.get("visual_evidence"):
        errors.append("visual_evidence is required")
    if not obj.get("rule") and obj.get("status") != "safe":
        errors.append("rule is required")
    return errors


def convert_reviews_to_records(output_dir: Path, append_to_db: bool, db_dir: Path, source_type: str) -> dict[str, Any]:
    draft_dir = output_dir / "draft_json"
    review_dir = output_dir / "review_decisions"
    accepted_dir = output_dir / "accepted_records"
    error_dir = output_dir / "errors"
    accepted_dir.mkdir(parents=True, exist_ok=True)
    error_dir.mkdir(parents=True, exist_ok=True)

    image_records: list[dict[str, Any]] = []
    object_records: list[dict[str, Any]] = []
    summary: dict[str, Any] = {"review_files": 0, "accepted_images": 0, "skipped_images": 0, "pending_images": 0, "accepted_objects": 0, "validation_errors": [], "errors": []}
    existing_sample_ids, existing_object_ids = read_existing_record_ids(db_dir)

    for review_path in sorted(review_dir.glob("*.review.json")):
        summary["review_files"] += 1
        review = load_json(review_path)
        sample_id = review.get("sample_id")
        draft_path = draft_dir / f"{sample_id}.json"
        if not draft_path.exists():
            summary["errors"].append({"review": review_path.as_posix(), "error": "missing draft json"})
            continue
        draft = load_json(draft_path)
        review = upgrade_review_with_draft(review, draft)

        image_decision = review.get("image_decision", "pending")
        if image_decision != "accept":
            if image_decision == "pending":
                summary["pending_images"] += 1
            else:
                summary["skipped_images"] += 1
            continue

        if sample_id in existing_sample_ids:
            summary["errors"].append({"review": review_path.as_posix(), "sample_id": sample_id, "error": "sample_id already exists in mother database"})
            continue

        # accept all objects from this image as-is from draft
        accepted_objects: list[dict[str, Any]] = []
        for item in review.get("objects", []):
            obj = {key: value for key, value in item.items() if key not in REVIEW_ONLY_KEYS}
            validation_errors = validate_accepted_object(obj)
            if validation_errors:
                summary["validation_errors"].append({"sample_id": sample_id, "object": item.get("draft_object_index"), "error": "; ".join(validation_errors)})
                continue
            accepted_objects.append(obj)

        if not accepted_objects:
            summary["errors"].append({"review": review_path.as_posix(), "error": "no valid objects after validation"})
            continue

        image_records.append(
            {
                "schema_version": SCHEMA_VERSION,
                "sample_id": sample_id,
                "image_path": draft["image_path"],
                "width": draft["width"],
                "height": draft["height"],
                "scene": "four_openings_edges",
                "source_type": source_type,
                "source_id": None,
                "split_group": None,
                "image_quality": "usable",
                "image_tags": [],
                "notes": review.get("review_note", ""),
            }
        )
        for index, obj in enumerate(accepted_objects, 1):
            object_instance_id = f"{sample_id}_obj_{index:02d}"
            if object_instance_id in existing_object_ids:
                summary["errors"].append({"sample_id": sample_id, "object_instance_id": object_instance_id, "error": "object_instance_id already exists in mother database"})
                continue
            object_records.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "object_instance_id": object_instance_id,
                    "sample_id": sample_id,
                    "object_id": obj["object_id"],
                    "object_name": obj["object_name"],
                    "gt_bbox": obj["bbox"],
                    "status": obj["status"],
                    "hazard_type_id": obj["hazard_type_id"],
                    "hazard_type": obj["hazard_type"],
                    "visual_evidence": obj["visual_evidence"],
                    "missing_evidence": obj["missing_evidence"],
                    "evidence_sufficiency": obj["evidence_sufficiency"],
                    "uncertainty_reason": obj["uncertainty_reason"],
                    "rule_id": obj.get("rule_id"),
                    "rule": obj["rule"],
                    "difficulty_tags": [],
                    "annotation_note": "",
                }
            )
        summary["accepted_images"] += 1
        summary["accepted_objects"] += len(accepted_objects)

    write_jsonl(accepted_dir / "images.jsonl", image_records)
    write_jsonl(accepted_dir / "objects.jsonl", object_records)
    if append_to_db and image_records:
        append_jsonl(db_dir / "images.jsonl", image_records)
        append_jsonl(db_dir / "objects.jsonl", object_records)
        summary["appended_to_db"] = True
    else:
        summary["appended_to_db"] = False
    write_json(accepted_dir / "commit_summary.json", summary)
    return summary


def read_existing_record_ids(db_dir: Path) -> tuple[set[str], set[str]]:
    sample_ids: set[str] = set()
    object_ids: set[str] = set()
    images_path = db_dir / "images.jsonl"
    objects_path = db_dir / "objects.jsonl"
    if images_path.exists():
        for line in images_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("sample_id"):
                sample_ids.add(record["sample_id"])
    if objects_path.exists():
        for line in objects_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("object_instance_id"):
                object_ids.add(record["object_instance_id"])
    return sample_ids, object_ids

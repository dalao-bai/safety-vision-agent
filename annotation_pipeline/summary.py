from __future__ import annotations

from collections import Counter
from typing import Any


def draft_summary(drafts: list[dict[str, Any]], errors: int) -> dict[str, Any]:
    object_counter: Counter[str] = Counter()
    status_counter: Counter[str] = Counter()
    uncertainty_counter: Counter[str] = Counter()
    warning_counter: Counter[str] = Counter()
    for draft in drafts:
        for obj in draft.get("objects", []):
            object_counter[obj.get("object_id") or "unknown"] += 1
            status_counter[obj.get("status") or "unknown"] += 1
            if obj.get("uncertainty_reason"):
                uncertainty_counter[obj["uncertainty_reason"]] += 1
            for warning in obj.get("validation_warnings") or []:
                warning_counter[warning] += 1
    return {
        "processed_images": len(drafts) + errors,
        "successful_drafts": len(drafts),
        "errors": errors,
        "object_distribution": dict(object_counter),
        "status_distribution": dict(status_counter),
        "uncertainty_reason_distribution": dict(uncertainty_counter),
        "draft_warning_distribution": dict(warning_counter),
    }


from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.vlm.detector import DetectionResult, Hazard


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _hazard_to_pipeline_object(h: Hazard) -> dict:
    return {
        "object_id": h.object_id,
        "object_name": h.object_name,
        "status": h.status,
        "hazard_type_id": h.hazard_type_id,
        "hazard_type": h.hazard_type,
        "bbox": h.bbox,
        "visual_evidence": h.visual_evidence,
        "evidence_sufficiency": h.evidence_sufficiency,
        "uncertainty_reason": h.uncertainty_reason,
        "missing_evidence": h.missing_evidence,
    }


def _hazard_snapshot(h: Hazard) -> dict:
    d = _hazard_to_pipeline_object(h)
    d["rule_basis"] = h.rule_basis
    d["reasoning_chain"] = h.reasoning_chain
    return d


class IntakeWriter:
    def __init__(self, intake_dir: str):
        self._dir = Path(intake_dir)

    def deposit(self, image_path: str, result: DetectionResult, note: str) -> str:
        src = Path(image_path)
        images = self._dir / "images"
        corrections = self._dir / "corrections"
        images.mkdir(parents=True, exist_ok=True)
        corrections.mkdir(parents=True, exist_ok=True)

        stem = f"{src.stem}_{uuid.uuid4().hex[:8]}"
        dest_img = images / f"{stem}{src.suffix.lower()}"
        shutil.copy2(src, dest_img)

        paired = {
            "sample_id": stem,
            "image_path": dest_img.as_posix(),
            "scene": result.scene,
            "objects": [_hazard_to_pipeline_object(h) for h in result.hazards],
            "agent_source": "agent_qa",
            "agent_correction_note": note,
        }
        (images / f"{stem}.json").write_text(
            json.dumps(paired, ensure_ascii=False, indent=2), encoding="utf-8")

        correction = {
            "source": "agent_qa",
            "created_at": _now(),
            "note": note,
            "original_vlm": {
                "scene": result.scene,
                "hazards": [_hazard_snapshot(h) for h in result.hazards],
            },
        }
        (corrections / f"{stem}.correction.json").write_text(
            json.dumps(correction, ensure_ascii=False, indent=2), encoding="utf-8")

        return str(self._dir)

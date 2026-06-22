from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class KGStore:
    def __init__(self, data: dict[str, Any], rule_blocks: list[dict[str, Any]] | None = None):
        self._data = data
        self._objects = {o["id"]: o for o in data.get("objects", [])}
        self._name_to_id = {o["name"]: o["id"] for o in data.get("objects", [])}
        self._hazard_types = {
            k: (v if isinstance(v, dict) else {"name": v})
            for k, v in data.get("hazard_types", {}).items()
        }
        self.scene = data.get("scene", {})
        # index rule blocks by object_id
        self._rule_blocks_by_object: dict[str, list[dict[str, Any]]] = {}
        for rb in (rule_blocks or []):
            self._rule_blocks_by_object.setdefault(rb.get("object_id", ""), []).append(rb)

    @classmethod
    def load(cls, path: str, rule_blocks_path: str | None = None) -> "KGStore":
        kg_path = Path(path)
        data = json.loads(kg_path.read_text(encoding="utf-8"))
        # default: sibling rule_blocks file next to the KG
        rb_path = Path(rule_blocks_path) if rule_blocks_path else kg_path.parent / "four_openings_edges_rule_blocks.json"
        rule_blocks: list[dict[str, Any]] = []
        if rb_path.exists():
            loaded = json.loads(rb_path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                rule_blocks = loaded
        return cls(data, rule_blocks)

    def get_object(self, object_id: str) -> dict[str, Any] | None:
        return self._objects.get(object_id)

    def object_id_for_name(self, name: str) -> str | None:
        return self._name_to_id.get(name)

    def get_hazard_type(self, hazard_type_id: str) -> dict[str, Any] | None:
        return self._hazard_types.get(hazard_type_id)

    def remediation_for(self, object_id: str) -> list[dict[str, str]]:
        """Positive compliance conditions (qualified_conditions). May be empty for
        objects whose rules live only in rule_blocks (e.g. foundation_pit)."""
        obj = self._objects.get(object_id)
        if not obj:
            return []
        items: list[dict[str, str]] = []
        for qc in obj.get("qualified_conditions", []):
            items.append({
                "id": qc.get("id", ""),
                "condition": qc.get("condition", ""),
                "source": qc.get("source", ""),
            })
        return items

    def rule_blocks_for(self, object_id: str, hazard_type_id: str | None = None) -> list[dict[str, Any]]:
        """Hazard rule blocks for an object, optionally filtered by hazard_type_id.
        Returns trimmed dicts useful for grounding remediation/standard answers."""
        blocks = self._rule_blocks_by_object.get(object_id, [])
        if hazard_type_id:
            blocks = [b for b in blocks if b.get("hazard_type_id") == hazard_type_id]
        return [{
            "rule_id": b.get("rule_id", ""),
            "hazard_type_id": b.get("hazard_type_id"),
            "hazard_type": b.get("hazard_type"),
            "rule_text": b.get("rule_text", ""),
            "visual_cues": b.get("visual_cues", []),
            "source": b.get("source", ""),
        } for b in blocks]

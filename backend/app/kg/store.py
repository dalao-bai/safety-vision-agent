from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class KGStore:
    """内存知识图谱：防护对象和隐患类型。"""

    def __init__(self, data: dict[str, Any]):
        self._data = data
        self._objects = {o["id"]: o for o in data.get("objects", [])}
        self._name_to_id = {o["name"]: o["id"] for o in data.get("objects", [])}
        self._hazard_types = {
            k: (v if isinstance(v, dict) else {"name": v})
            for k, v in data.get("hazard_types", {}).items()
        }
        self.scene = data.get("scene", {})

    @classmethod
    def load(cls, path: str) -> "KGStore":
        kg_path = Path(path)
        data = json.loads(kg_path.read_text(encoding="utf-8"))
        return cls(data)

    def get_object(self, object_id: str) -> dict[str, Any] | None:
        return self._objects.get(object_id)

    def object_id_for_name(self, name: str) -> str | None:
        # 精确匹配
        if name in self._name_to_id:
            return self._name_to_id[name]
        # 模糊匹配：KG名称包含输入名，或输入名包含KG名称
        for kg_name, kg_id in self._name_to_id.items():
            if name in kg_name or kg_name in name:
                return kg_id
        return None

    def get_hazard_type(self, hazard_type_id: str) -> dict[str, Any] | None:
        return self._hazard_types.get(hazard_type_id)

    def remediation_for(self, object_id: str) -> list[dict[str, str]]:
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

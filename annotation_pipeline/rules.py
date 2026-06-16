from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any
import re

from .constants import OBJECT_TYPES
from .io_utils import load_json


class RuleStore:
    def __init__(self, rules: list[dict[str, Any]]) -> None:
        self.rules = rules
        self.by_id = {rule["rule_id"]: rule for rule in rules if rule.get("rule_id")}
        self.by_object: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for rule in rules:
            object_id = rule.get("object_id")
            if object_id:
                self.by_object[object_id].append(rule)

    @classmethod
    def load(cls, path: Path) -> "RuleStore":
        data = load_json(path)
        if not isinstance(data, list):
            raise ValueError(f"rule blocks must be a list: {path}")
        return cls(data)

    def prompt_context(self) -> str:
        parts = []
        for object_id, object_name in OBJECT_TYPES:
            rules = self.by_object.get(object_id, [])
            parts.append(f"\n## {object_id} / {object_name}")
            for rule in rules:
                status = rule.get("status_target")
                hazard = rule.get("hazard_type_id") or "none"
                parts.append(f"- {status} / {hazard}: {rule.get('rule_text', '')}")
                cues = rule.get("visual_cues") or []
                if cues:
                    parts.append(f"  视觉线索: {'; '.join(str(c) for c in cues)}")
        return "\n".join(parts)

    def object_types(self) -> list[tuple[str, str]]:
        seen: set[str] = set()
        items: list[tuple[str, str]] = []
        for rule in self.rules:
            object_id = rule.get("object_id")
            object_name = rule.get("object_name")
            if not object_id or object_id == "*" or object_id in seen:
                continue
            seen.add(str(object_id))
            items.append((str(object_id), str(object_name or object_id)))
        return items or OBJECT_TYPES

    def hazard_types(self) -> list[tuple[str, str]]:
        seen: set[str] = set()
        items: list[tuple[str, str]] = []
        for rule in self.rules:
            hazard_type_id = rule.get("hazard_type_id")
            hazard_type = rule.get("hazard_type")
            if not hazard_type_id or hazard_type_id in seen:
                continue
            seen.add(str(hazard_type_id))
            items.append((str(hazard_type_id), str(hazard_type or hazard_type_id)))
        return items

    def choose_rule(self, obj: dict[str, Any]) -> tuple[str | None, str, list[str]]:
        warnings: list[str] = []
        rule_text = obj.get("rule")
        if isinstance(rule_text, str) and rule_text.strip():
            return self.rule_id_for_text(rule_text.strip())[0] if self.rule_id_for_text(rule_text.strip()) else None, rule_text.strip(), warnings

        for rule_id in obj.get("rule_ids") or []:
            rule = self.by_id.get(rule_id)
            if rule and rule.get("rule_text"):
                return str(rule["rule_id"]), str(rule["rule_text"]), warnings

        object_id = obj.get("object_id")
        status = obj.get("status")
        hazard_type_id = obj.get("hazard_type_id")
        candidates = self.matching_candidates(object_id, status, hazard_type_id)
        if candidates:
            rule = self.best_rule(candidates, str(obj.get("visual_evidence") or ""))
            return str(rule.get("rule_id") or ""), str(rule.get("rule_text") or ""), warnings

        warnings.append("no_matching_rule_text")
        return None, "", warnings

    def matching_candidates(self, object_id: Any, status: Any, hazard_type_id: Any) -> list[dict[str, Any]]:
        candidates = []
        for rule in self.by_object.get(object_id, []):
            if rule.get("status_target") != status:
                continue
            if status == "confirmed_hazard" and rule.get("hazard_type_id") != hazard_type_id:
                continue
            candidates.append(rule)
        if candidates or status != "uncertain":
            return candidates
        return [rule for rule in self.by_object.get("*", []) if rule.get("status_target") == "uncertain"]

    def best_rule(self, candidates: list[dict[str, Any]], visual_evidence: str) -> dict[str, Any]:
        if len(candidates) == 1:
            return candidates[0]
        evidence_tokens = tokenize(visual_evidence)
        scored = [(self.rule_score(rule, evidence_tokens), index, rule) for index, rule in enumerate(candidates)]
        scored.sort(key=lambda item: (-item[0], item[1]))
        return scored[0][2]

    def rule_score(self, rule: dict[str, Any], evidence_tokens: set[str]) -> int:
        score = 0
        cue_tokens: set[str] = set()
        for cue in rule.get("visual_cues") or []:
            cue_tokens.update(tokenize(str(cue)))
        rule_tokens = tokenize(str(rule.get("rule_text") or ""))
        score += 3 * len(evidence_tokens & cue_tokens)
        score += len(evidence_tokens & rule_tokens)
        return score

    def rule_id_for_text(self, rule_text: str) -> list[str]:
        if not rule_text:
            return []
        for rule in self.rules:
            if rule.get("rule_text") == rule_text:
                return [str(rule["rule_id"])]
        return []


def tokenize(text: str) -> set[str]:
    tokens = set(re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}", text))
    # Add overlapping Chinese bigrams so short visual terms can match longer rule text.
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
    for index in range(len(chinese_chars) - 1):
        tokens.add("".join(chinese_chars[index : index + 2]))
    return tokens

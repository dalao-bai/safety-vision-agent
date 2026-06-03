from __future__ import annotations


SCHEMA_VERSION = "foe_annotation_v1.0"
DRAFT_SCHEMA_VERSION = "api_annotation_draft_v1.0"

OBJECT_TYPES = [
    ("stair_opening_protection", "楼梯口防护"),
    ("elevator_shaft_protection", "电梯井口防护"),
    ("reserved_opening_protection", "预留洞口防护"),
    ("passage_entrance_protection", "通道口防护"),
    ("balcony_edge_protection", "阳台临边防护"),
    ("roof_edge_protection", "屋面临边防护"),
    ("floor_edge_protection", "楼层临边防护"),
    ("foundation_pit_edge_protection", "基坑临边防护"),
    ("ramp_edge_protection", "跑道/斜道临边防护"),
]

HAZARD_TYPES = [
    ("missing_protection", "防护缺失"),
    ("discontinuous_protection", "防护不连续/不严密"),
    ("temporary_substitute", "临时替代防护"),
    ("unfixed_or_weak_protection", "固定不牢/强度不足"),
    ("opening_uncovered", "洞口敞开"),
    ("cover_unfixed_or_insufficient", "盖板未固定/覆盖不足"),
    ("door_open_or_missing", "防护门缺失/未关闭"),
    ("canopy_missing_or_invalid", "通道口防护棚缺失/失效"),
    ("access_or_obstruction_issue", "通行/障碍异常"),
]

UNCERTAINTY_REASONS = [
    "protective_component_not_visible",
    "visual_rule_evidence_insufficient",
    "external_context_required",
]

OBJECT_NAME_BY_ID = dict(OBJECT_TYPES)
OBJECT_ID_BY_NAME = {name: oid for oid, name in OBJECT_TYPES}
HAZARD_NAME_BY_ID = dict(HAZARD_TYPES)
HAZARD_ID_BY_NAME = {name: hid for hid, name in HAZARD_TYPES}

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

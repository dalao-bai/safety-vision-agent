from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Message:
    id: int
    session_id: int
    role: str
    content: str
    created_at: str


@dataclass
class ImageRecord:
    id: int
    session_id: int
    path: str
    scene: str
    status: str
    created_at: str


@dataclass
class Hazard:
    id: int
    image_id: int
    object_id: str
    status: str
    hazard_type_id: str | None
    bbox: list[int] | None
    reasoning_chain: list[dict[str, Any]] = field(default_factory=list)
    visual_evidence: str = ""
    rule_basis: str = ""
    evidence_sufficiency: str = ""
    confirmed: bool = False


@dataclass
class Correction:
    id: int
    image_id: int
    note: str
    intake_path: str
    created_at: str

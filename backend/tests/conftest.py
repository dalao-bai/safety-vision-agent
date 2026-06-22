import json
import struct
import zlib
from pathlib import Path

import pytest


def _tiny_png_bytes(width: int = 1000, height: int = 1000) -> bytes:
    """Minimal valid 1000x1000 grayscale PNG (real deflate of zero rows)."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)  # 8-bit grayscale
    raw = bytearray()
    for _ in range(height):
        raw.append(0)  # filter type 0
        raw.extend(b"\x00" * width)
    idat = zlib.compress(bytes(raw), 1)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


@pytest.fixture
def tiny_png(tmp_path: Path) -> Path:
    p = tmp_path / "site.png"
    p.write_bytes(_tiny_png_bytes())
    return p


@pytest.fixture
def sample_vlm_hazard() -> dict:
    """The single-hazard object the user provided."""
    return {
        "scene": "四口五临边",
        "reasoning_chain": [
            {"step": "observe", "content": "图中可见基坑开挖形成较深临边……"},
            {"step": "locate", "content": "定位到基坑临边防护……"},
            {"step": "match_rule", "content": "对照候选隐患条款……可判定为防护缺失。"},
            {"step": "assess", "content": "关键隐患证据在图中清晰可见,证据充分。"},
        ],
        "related_object": "基坑临边防护",
        "object_bbox": [0, 278, 999, 999],
        "visual_evidence": "图中可见基坑开挖形成较深临边,坑边及作业面周边未见连续防护设施。",
        "rule_basis": "开挖深度2m及以上……未设置防护栏杆……人员可直接接近坠落边缘。",
        "evidence_sufficiency": "sufficient",
        "uncertainty_reason": None,
        "hazard_type_id": "missing_protection",
        "hazard_type": "防护缺失",
        "status": "confirmed_hazard",
    }


@pytest.fixture
def sample_vlm_response(sample_vlm_hazard) -> dict:
    """Whole-image conclusion + hazard list, as the real model returns."""
    return {"scene": "四口五临边", "hazards": [sample_vlm_hazard]}


@pytest.fixture
def repo_root() -> Path:
    # backend/tests/conftest.py -> repo root is two levels up from backend/
    return Path(__file__).resolve().parents[2]


@pytest.fixture
def kg_path(repo_root: Path) -> Path:
    return repo_root / "知识图谱主文件" / "four_openings_edges_kg_v2.json"

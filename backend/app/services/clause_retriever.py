# backend/app/services/clause_retriever.py
"""四口五临边隐患 → 官方条款 的混合检索。

确定性主路径：
  related_object(中文) → object_id → 按 (object_id,status,hazard_type_id) 命中 rule_blocks
  → 从命中条目的 source 解析出 (标准码, 条号) → 按条号从标准 markdown 取完整原文。
语义 RAG 兜底：仅当注入 semantic_search 且确定性无命中时启用（本期默认 None）。

纯函数（normalize_code/parse_sources/extract_clause）单独可测；ClauseRetriever 组装。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.models.foe_schemas import ClauseRef, FoeObject

# backend/app/services/clause_retriever.py → parents[3] = 仓库根
_REPO_ROOT = Path(__file__).resolve().parents[3]

_STD_CODE = re.compile(r"JGJ\s*\d+-\d+")
_CLAUSE_REF = re.compile(r"第(\d+\.\d+(?:\.\d+)?)条")


def normalize_code(code: str) -> str:
    """折叠空白：'JGJ  80-2016' → 'JGJ 80-2016'。"""
    return re.sub(r"\s+", " ", code).strip()


def parse_sources(source: str) -> list[tuple[str, str]]:
    """从 rule_blocks 的 source 自由文本里提取 (标准码, 条号) 列表。

    标准码与条号按出现位置排序；每个条号归属于其前方最近的标准码。
    去重并保持出现顺序。
    """
    events: list[tuple[int, str, str]] = []
    for m in _STD_CODE.finditer(source):
        events.append((m.start(), "std", normalize_code(m.group())))
    for m in _CLAUSE_REF.finditer(source):
        events.append((m.start(), "clause", m.group(1)))
    events.sort(key=lambda e: e[0])

    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    current_std: str | None = None
    for _pos, kind, val in events:
        if kind == "std":
            current_std = val
        elif kind == "clause" and current_std:
            pair = (current_std, val)
            if pair not in seen:
                seen.add(pair)
                out.append(pair)
    return out


def extract_clause(markdown_text: str, clause_num: str) -> str | None:
    """从标准 markdown 抽取某条号的完整原文（到下一条号为止）。

    条文行首形如 '# 4.1.1坠落…' 或 '4.1.2施工…'。clause_num 形如 '4.1.1'。
    """
    start_pat = re.compile(r"^\s*#*\s*" + re.escape(clause_num) + r"(?!\.\d)(?=\D|$)")
    next_pat = re.compile(r"^\s*#*\s*\d+\.\d+(?:\.\d+)?(?=\D)")
    lines = markdown_text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if start_pat.match(line):
            start = i
            break
    if start is None:
        return None
    first = re.sub(r"^\s*#*\s*" + re.escape(clause_num) + r"\s*", "", lines[start]).strip()
    buf = [first] if first else []
    for line in lines[start + 1:]:
        if next_pat.match(line):
            break
        if line.strip():
            buf.append(line.strip())
    text = "\n".join(buf).strip()
    return text or None

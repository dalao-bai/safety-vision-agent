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


class ClauseRetriever:
    """混合条款检索器。构造接受已加载数据(便于测试)，load() 从文件构造。"""

    def __init__(
        self,
        rule_blocks: list[dict],
        standards: dict[str, str],
        clause_index: str = "",
        semantic_search=None,
    ):
        self.rule_blocks = rule_blocks
        self.standards = standards          # {标准码: markdown 全文}
        self.clause_index = clause_index    # 四口五临边标准引用索引.md 全文
        self.semantic_search = semantic_search
        self.name2id: dict[str, str] = {}
        self._by_key: dict[tuple, list[dict]] = {}
        for r in rule_blocks:
            oid, oname = r.get("object_id"), r.get("object_name")
            if oid and oname:
                self.name2id[oname] = oid
            key = (r.get("object_id"), r.get("status_target"), r.get("hazard_type_id"))
            self._by_key.setdefault(key, []).append(r)

    @classmethod
    def load(cls, settings) -> "ClauseRetriever":
        """从配置路径加载 rule_blocks + 标准 markdown + 索引。"""
        rb_path = _REPO_ROOT / settings.foe_rule_blocks
        rule_blocks = json.loads(rb_path.read_text(encoding="utf-8-sig"))

        standards: dict[str, str] = {}
        mineru = _REPO_ROOT / settings.foe_standards_dir / "MinerU识别结果"
        if mineru.exists():
            for md in mineru.glob("*/ocr/*.md"):
                m = _STD_CODE.search(md.name)
                if m:
                    standards[normalize_code(m.group())] = md.read_text(encoding="utf-8")

        clause_index = ""
        idx = _REPO_ROOT / settings.foe_clause_index
        if idx.exists():
            clause_index = idx.read_text(encoding="utf-8")

        return cls(rule_blocks, standards, clause_index)

    def match_rules(self, object_id, status, hazard_type_id) -> list[dict]:
        return self._by_key.get((object_id, status, hazard_type_id), [])

    def clause_text(self, code: str, clause_num: str) -> str | None:
        md = self.standards.get(code)
        if md:
            text = extract_clause(md, clause_num)
            if text:
                return text
        # 索引兜底：找 "第x.y.z条" 所在行
        if self.clause_index:
            marker = f"第{clause_num}条"
            i = self.clause_index.find(marker)
            if i != -1:
                line = self.clause_index[i:].splitlines()[0].strip()
                return line or None
        return None

    def retrieve(self, obj: FoeObject) -> list[ClauseRef]:
        object_id = self.name2id.get(obj.related_object, obj.related_object)
        rules = self.match_rules(object_id, obj.status, obj.hazard_type_id)
        if not rules and obj.rule_basis:
            rules = [r for r in self.rule_blocks if r.get("rule_text") == obj.rule_basis]

        refs: list[ClauseRef] = []
        seen: set[tuple[str, str]] = set()
        for r in rules:
            src = r.get("source") or ""
            for code, clause_num in parse_sources(src):
                if (code, clause_num) in seen:
                    continue
                seen.add((code, clause_num))
                text = self.clause_text(code, clause_num)
                if text:
                    refs.append(ClauseRef(
                        standard_code=code,
                        clause_id=f"第{clause_num}条",
                        official_text=text,
                        paraphrase=r.get("rule_text"),
                        source_raw=src,
                    ))

        if not refs and self.semantic_search and obj.rule_basis:
            for hit in self.semantic_search(obj.rule_basis):
                refs.append(ClauseRef(
                    standard_code=hit.get("standard_code", ""),
                    clause_id=hit.get("clause_id", ""),
                    official_text=hit.get("text", ""),
                    paraphrase=obj.rule_basis,
                    source_raw="semantic",
                ))
        return refs

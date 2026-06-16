# 四口五临边条款报告 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增"消费四口五临边 VLM 输出 → 混合检索官方条款 → 生成 .docx 报告"的后端能力，用样例 JSON 即可端到端测试。

**Architecture:** 新增独立模块（schema / 检索器 / 报告渲染 / 端点），不触碰现有旧 `AnalysisResult` 分析链。检索用"确定性映射(对象+状态+隐患→rule_blocks→条文编号) + 按编号取标准 markdown 原文"，语义 RAG 作可选兜底（本期不接网络）。报告复用 python-docx；端点复刻现有 report 的三段式（生成/轮询/下载），但用 FOE 自己的任务注册表以保证下载链接正确。

**Tech Stack:** FastAPI · Pydantic v2 · python-docx · 纯 Python 正则解析（无新依赖）· pytest

依据设计：`docs/superpowers/specs/2026-06-16-foe-clause-report-design.md`

---

## File Structure

| 文件 | 职责 | 新建/修改 |
|---|---|---|
| `backend/app/models/foe_schemas.py` | 新 VLM 输出契约：ReasoningStep/FoeObject/FoeAnalysis/ClauseRef/FoeReportRequest | 新建 |
| `backend/app/services/clause_retriever.py` | 混合条款检索：对象映射 · source 解析 · 标准 markdown 取条文 · retrieve() | 新建 |
| `backend/app/services/foe_report_generator.py` | .docx 渲染 + FOE 专属进程内任务注册表 | 新建 |
| `backend/app/api/routes/foe_report.py` | POST /api/foe/report · GET status · GET download | 新建 |
| `backend/app/core/config.py` | 新增 foe_* 资产路径配置 | 修改 |
| `backend/app/api/dependencies.py` | get_clause_retriever() 应用级单例 | 修改 |
| `backend/app/main.py` | 注册 foe_report 路由 | 修改 |
| `backend/tests/test_foe_schemas.py` | schema 测试 | 新建 |
| `backend/tests/test_clause_retriever.py` | 检索器测试 | 新建 |
| `backend/tests/test_foe_report_generator.py` | 报告渲染测试 | 新建 |
| `backend/tests/test_foe_report_route.py` | 端点集成测试 | 新建 |

所有命令默认在 `backend/` 目录下执行。

---

## Task 1: 新 VLM 输出 schema

**Files:**
- Create: `backend/app/models/foe_schemas.py`
- Test: `backend/tests/test_foe_schemas.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_foe_schemas.py
from app.models.foe_schemas import FoeAnalysis, FoeObject, ReasoningStep

EXAMPLE_OBJECT = {
    "scene": "四口五临边",
    "reasoning_chain": [
        {"step": "observe", "content": "图中可见基坑开挖形成较深临边…"},
        {"step": "locate", "content": "定位到基坑临边防护…"},
        {"step": "match_rule", "content": "对照候选隐患条款…据此可判定为防护缺失。"},
        {"step": "assess", "content": "证据充分，可下确定判断。"},
    ],
    "related_object": "基坑临边防护",
    "object_bbox": [0, 278, 999, 999],
    "visual_evidence": "图中可见基坑开挖形成较深临边…",
    "rule_basis": "开挖深度2m及以上…未设置防护栏杆…",
    "evidence_sufficiency": "sufficient",
    "uncertainty_reason": None,
    "hazard_type_id": "missing_protection",
    "hazard_type": "防护缺失",
    "status": "confirmed_hazard",
}


def test_foe_object_parses_example():
    obj = FoeObject.model_validate(EXAMPLE_OBJECT)
    assert obj.related_object == "基坑临边防护"
    assert obj.object_bbox == [0, 278, 999, 999]
    assert obj.status == "confirmed_hazard"
    assert obj.hazard_type_id == "missing_protection"
    assert len(obj.reasoning_chain) == 4
    assert obj.reasoning_chain[0].step == "observe"


def test_foe_analysis_wraps_object_list():
    analysis = FoeAnalysis.model_validate(
        {"image_ref": "/tmp/x.png", "objects": [EXAMPLE_OBJECT, EXAMPLE_OBJECT]}
    )
    assert len(analysis.objects) == 2
    assert isinstance(analysis.objects[0], FoeObject)


def test_foe_object_ignores_extra_scene_field():
    # 顶层 example 带 scene，FoeObject 不声明它；额外字段应被忽略不报错
    obj = FoeObject.model_validate(EXAMPLE_OBJECT)
    assert isinstance(obj, FoeObject)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_foe_schemas.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.foe_schemas'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/models/foe_schemas.py
"""四口五临边微调模型的输出契约 + 报告检索结果类型。

与旧 app/models/schemas.py 的 AnalysisResult 并存：本文件是新 schema 的落地起点，
将来 analyze_image 换微调模型后产出 FoeAnalysis。本期仅供报告/检索消费。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ReasoningStep(BaseModel):
    """思维链一步：observe / locate / match_rule / assess。"""
    step: str
    content: str


class FoeObject(BaseModel):
    """一个被识别的四口五临边对象及其隐患判定。多余字段(如 scene)忽略。"""
    related_object: str
    object_bbox: list[int] = Field(default_factory=list)
    status: str  # confirmed_hazard | safe | uncertain
    hazard_type_id: str | None = None
    hazard_type: str | None = None
    visual_evidence: str = ""
    rule_basis: str | None = None
    evidence_sufficiency: str | None = None
    uncertainty_reason: str | None = None
    reasoning_chain: list[ReasoningStep] = Field(default_factory=list)


class FoeAnalysis(BaseModel):
    """一张图的分析结果：一图多对象。"""
    image_ref: str | None = None
    width: int | None = None
    height: int | None = None
    objects: list[FoeObject] = Field(default_factory=list)


class ClauseRef(BaseModel):
    """检索到的官方条款引用。"""
    standard_code: str          # 如 "JGJ 80-2016"
    clause_id: str              # 如 "第4.1.1条"
    official_text: str          # 标准原文
    paraphrase: str | None = None   # rule_blocks 的 rule_text（口径摘要）
    source_raw: str = ""        # 原始 source 串，便于溯源


class FoeReportRequest(BaseModel):
    """报告生成请求体。"""
    analyses: list[FoeAnalysis] = Field(default_factory=list)
    title: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_foe_schemas.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/foe_schemas.py backend/tests/test_foe_schemas.py
git commit -m "feat(foe): add four-openings/edges VLM output + clause schemas"
```

---

## Task 2: 检索器纯函数（source 解析 + 条文抽取 + 对象映射）

**Files:**
- Create: `backend/app/services/clause_retriever.py`
- Test: `backend/tests/test_clause_retriever.py`

本任务只实现可独立测试的纯函数；retrieve() 在 Task 3 组装。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_clause_retriever.py
from app.services.clause_retriever import (
    extract_clause,
    normalize_code,
    parse_sources,
)

SOURCE = (
    "标准规范文件/MinerU识别结果/JGJ 59-2011 建筑施工安全检查标准/ocr/"
    "JGJ 59-2011 建筑施工安全检查标准.md 第3.11.3条'安全防护'；"
    "标准规范文件/结构化表格/JGJ59-2011_表B.13_高处作业检查评分表.md 临边防护；"
    "标准规范文件/MinerU识别结果/JGJ 80-2016 建筑施工高处作业安全技术规范/ocr/"
    "JGJ 80-2016 建筑施工高处作业安全技术规范.md 第4.1.1条、第4.3.1条"
)

STD_MD = """# 4 临边与洞口作业
# 4.1.1坠落高度基准面2m及以上进行临边作业时，应在临空一侧设置防护栏杆。
4.1.2施工的楼梯口、楼梯平台和梯段边，应安装防护栏杆；
4.3.1临边作业的防护栏杆应由横杆、立杆及挡脚板组成。
4.3.2其他要求。
"""


def test_normalize_code_collapses_spaces():
    assert normalize_code("JGJ  80-2016") == "JGJ 80-2016"


def test_parse_sources_attributes_clauses_to_nearest_standard():
    pairs = parse_sources(SOURCE)
    assert ("JGJ 59-2011", "3.11.3") in pairs
    assert ("JGJ 80-2016", "4.1.1") in pairs
    assert ("JGJ 80-2016", "4.3.1") in pairs
    # 4.1.1 / 4.3.1 必须归到 JGJ 80-2016，而非 59
    assert ("JGJ 59-2011", "4.1.1") not in pairs


def test_extract_clause_returns_full_text_until_next_clause():
    text = extract_clause(STD_MD, "4.1.1")
    assert text.startswith("坠落高度基准面2m及以上")
    assert "4.1.2" not in text  # 到下一条为止


def test_extract_clause_missing_returns_none():
    assert extract_clause(STD_MD, "9.9.9") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_clause_retriever.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.clause_retriever'`

- [ ] **Step 3: Write minimal implementation**

```python
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
    start_pat = re.compile(r"^\s*#*\s*" + re.escape(clause_num) + r"(?=\D)")
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_clause_retriever.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/clause_retriever.py backend/tests/test_clause_retriever.py
git commit -m "feat(foe): clause-retriever pure helpers (source parse, clause extract)"
```

---

## Task 3: ClauseRetriever 类 + retrieve()

**Files:**
- Modify: `backend/app/services/clause_retriever.py` (append class)
- Test: `backend/tests/test_clause_retriever.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_clause_retriever.py  (append)
from app.models.foe_schemas import FoeObject
from app.services.clause_retriever import ClauseRetriever

RULE_BLOCKS = [
    {
        "rule_id": "foundation_pit_edge_protection_H1",
        "object_id": "foundation_pit_edge_protection",
        "object_name": "基坑临边防护",
        "status_target": "confirmed_hazard",
        "hazard_type_id": "missing_protection",
        "rule_text": "开挖深度2m及以上…未设置防护栏杆…",
        "source": (
            "…/JGJ 80-2016 建筑施工高处作业安全技术规范.md 第4.1.1条、第4.3.1条"
        ),
    }
]
STANDARDS = {"JGJ 80-2016": STD_MD}


def _retriever():
    return ClauseRetriever(rule_blocks=RULE_BLOCKS, standards=STANDARDS, clause_index="")


def test_name_to_id_mapping():
    r = _retriever()
    assert r.name2id["基坑临边防护"] == "foundation_pit_edge_protection"


def test_retrieve_returns_official_clause_text():
    r = _retriever()
    obj = FoeObject.model_validate(
        {
            "related_object": "基坑临边防护",
            "object_bbox": [0, 0, 1, 1],
            "status": "confirmed_hazard",
            "hazard_type_id": "missing_protection",
            "visual_evidence": "x",
        }
    )
    refs = r.retrieve(obj)
    ids = {(ref.standard_code, ref.clause_id) for ref in refs}
    assert ("JGJ 80-2016", "第4.1.1条") in ids
    assert ("JGJ 80-2016", "第4.3.1条") in ids
    first = next(ref for ref in refs if ref.clause_id == "第4.1.1条")
    assert first.official_text.startswith("坠落高度基准面2m及以上")


def test_retrieve_no_match_returns_empty():
    r = _retriever()
    obj = FoeObject.model_validate(
        {"related_object": "未知对象", "object_bbox": [0, 0, 1, 1],
         "status": "safe", "visual_evidence": "x"}
    )
    assert r.retrieve(obj) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_clause_retriever.py -v`
Expected: FAIL — `ImportError: cannot import name 'ClauseRetriever'`

- [ ] **Step 3: Write minimal implementation**

Append to `backend/app/services/clause_retriever.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_clause_retriever.py -v`
Expected: PASS (7 passed total)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/clause_retriever.py backend/tests/test_clause_retriever.py
git commit -m "feat(foe): ClauseRetriever with deterministic hybrid retrieve()"
```

---

## Task 4: 报告渲染 + FOE 任务注册表

**Files:**
- Create: `backend/app/services/foe_report_generator.py`
- Test: `backend/tests/test_foe_report_generator.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_foe_report_generator.py
import os

from docx import Document

from app.models.foe_schemas import ClauseRef, FoeAnalysis, FoeObject
from app.services import foe_report_generator as foe


class _FakeRetriever:
    def retrieve(self, obj):
        return [ClauseRef(
            standard_code="JGJ 80-2016", clause_id="第4.1.1条",
            official_text="坠落高度基准面2m及以上进行临边作业时，应设置防护栏杆。",
            paraphrase="未设防护", source_raw="x",
        )]


def _analysis():
    return FoeAnalysis(objects=[FoeObject(
        related_object="基坑临边防护", object_bbox=[0, 0, 1, 1],
        status="confirmed_hazard", hazard_type_id="missing_protection",
        hazard_type="防护缺失", visual_evidence="坑边无栏杆",
    )])


def test_generate_report_creates_docx_with_clause(tmp_path):
    path = foe.generate_foe_report_docx(
        [_analysis()], _FakeRetriever(), str(tmp_path), title="测试报告"
    )
    assert os.path.exists(path)
    doc = Document(path)
    full = "\n".join(p.text for p in doc.paragraphs)
    assert "基坑临边防护" in full
    assert "JGJ 80-2016 第4.1.1条" in full
    assert "防护缺失" in full


def test_task_registry_roundtrip():
    tid = foe.create_task("user-1")
    assert foe.get_task(tid)["status"] == "pending"
    foe.set_task_done(tid, "/tmp/r.docx")
    view = foe.get_task(tid)
    assert view["status"] == "done"
    assert view["download_url"] == f"/api/foe/report/download/{tid}"
    assert view["user_id"] == "user-1"


def test_unknown_task_returns_none():
    assert foe.get_task("nope") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_foe_report_generator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.foe_report_generator'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/foe_report_generator.py
"""四口五临边报告渲染 (.docx) + FOE 专属进程内任务注册表。

独立于 report_generator 的任务注册表，以保证下载链接指向 /api/foe/report/download。
"""

from __future__ import annotations

import os
import uuid
from typing import Any

from docx import Document
from docx.shared import Inches

from app.models.foe_schemas import FoeAnalysis

_STATUS_LABELS = {"confirmed_hazard": "确认隐患", "safe": "安全", "uncertain": "不确定"}
_STEP_LABELS = {"observe": "观察", "locate": "定位", "match_rule": "匹配规则", "assess": "评估"}
_IMAGE_WIDTH = Inches(3.5)


def generate_foe_report_docx(
    analyses: list[FoeAnalysis], retriever, output_dir: str, title: str | None = None
) -> str:
    """生成 .docx 报告，返回绝对路径。retriever 须有 retrieve(FoeObject)->[ClauseRef]。"""
    os.makedirs(output_dir, exist_ok=True)
    doc = Document()
    doc.add_heading(title or "四口五临边安全隐患报告", level=0)

    total_objs = sum(len(a.objects) for a in analyses)
    hazard_objs = sum(1 for a in analyses for o in a.objects if o.status == "confirmed_hazard")
    doc.add_paragraph(f"图片数：{len(analyses)}")
    doc.add_paragraph(f"识别对象数：{total_objs}")
    doc.add_paragraph(f"其中确认隐患：{hazard_objs}")

    for idx, analysis in enumerate(analyses, 1):
        doc.add_heading(f"图片 {idx}", level=1)
        ref_path = analysis.image_ref
        if ref_path and os.path.exists(ref_path):
            try:
                doc.add_picture(ref_path, width=_IMAGE_WIDTH)
            except Exception as exc:  # noqa: BLE001 - 缺图不应中断报告
                doc.add_paragraph(f"（图片无法嵌入：{ref_path}，{exc}）")

        if not analysis.objects:
            doc.add_paragraph("未识别到四口五临边对象。")
            continue

        for obj in analysis.objects:
            doc.add_heading(obj.related_object, level=2)
            doc.add_paragraph(f"状态：{_STATUS_LABELS.get(obj.status, obj.status)}")
            if obj.hazard_type:
                doc.add_paragraph(f"隐患类型：{obj.hazard_type}")
            doc.add_paragraph(f"边界框：{obj.object_bbox}")
            if obj.reasoning_chain:
                doc.add_paragraph("推理过程：")
                for step in obj.reasoning_chain:
                    label = _STEP_LABELS.get(step.step, step.step)
                    doc.add_paragraph(f"{label}：{step.content}")
            if obj.visual_evidence:
                doc.add_paragraph(f"视觉证据：{obj.visual_evidence}")
            if obj.evidence_sufficiency:
                doc.add_paragraph(f"证据充分性：{obj.evidence_sufficiency}")
            if obj.status == "uncertain" and obj.uncertainty_reason:
                doc.add_paragraph(f"不确定原因：{obj.uncertainty_reason}")

            refs = retriever.retrieve(obj)
            if refs:
                doc.add_paragraph("依据条款：")
                for ref in refs:
                    para = doc.add_paragraph()
                    para.add_run(f"【{ref.standard_code} {ref.clause_id}】").bold = True
                    para.add_run(ref.official_text)
            else:
                doc.add_paragraph("（未匹配到条款，建议人工复核）")

    filename = uuid.uuid4().hex + ".docx"
    out_path = os.path.abspath(os.path.join(output_dir, filename))
    doc.save(out_path)
    return out_path


# --- FOE 专属进程内任务注册表 -----------------------------------------------
_TASKS: dict[str, dict[str, Any]] = {}


def create_task(user_id: str) -> str:
    task_id = uuid.uuid4().hex
    _TASKS[task_id] = {"status": "pending", "user_id": user_id, "path": None, "error": None}
    return task_id


def set_task_done(task_id: str, path: str) -> None:
    task = _TASKS.get(task_id)
    if task is not None:
        task["status"] = "done"
        task["path"] = path


def set_task_error(task_id: str, msg: str) -> None:
    task = _TASKS.get(task_id)
    if task is not None:
        task["status"] = "error"
        task["error"] = msg


def get_task(task_id: str) -> dict[str, Any] | None:
    task = _TASKS.get(task_id)
    if task is None:
        return None
    view: dict[str, Any] = {"status": task["status"], "user_id": task["user_id"]}
    if task["status"] == "done":
        view["download_url"] = f"/api/foe/report/download/{task_id}"
        view["path"] = task["path"]
    elif task["status"] == "error":
        view["error"] = task["error"]
    return view
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_foe_report_generator.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/foe_report_generator.py backend/tests/test_foe_report_generator.py
git commit -m "feat(foe): docx report renderer + FOE task registry"
```

---

## Task 5: 配置 + 检索器单例

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/api/dependencies.py`
- Test: `backend/tests/test_clause_retriever.py` (append load 测试)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_clause_retriever.py  (append)
from app.core.config import get_settings
from app.services.clause_retriever import ClauseRetriever


def test_load_reads_real_assets():
    """用仓库内真实资产构造检索器，验证默认路径正确、规则已加载。"""
    r = ClauseRetriever.load(get_settings())
    assert r.name2id.get("基坑临边防护") == "foundation_pit_edge_protection"
    assert "JGJ 80-2016" in r.standards
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_clause_retriever.py::test_load_reads_real_assets -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'foe_rule_blocks'`

- [ ] **Step 3: Write minimal implementation**

In `backend/app/core/config.py`, add inside `class Settings` (after the regulation/annotation fields, before the closing of the class):

```python
    # v0.3 四口五临边条款报告：资产路径（相对仓库根）。
    foe_rule_blocks: str = Field(
        "知识图谱主文件/four_openings_edges_rule_blocks.json", alias="FOE_RULE_BLOCKS"
    )
    foe_standards_dir: str = Field(
        "知识图谱主文件/标准规范文件", alias="FOE_STANDARDS_DIR"
    )
    foe_clause_index: str = Field(
        "知识图谱主文件/标准规范文件/四口五临边标准引用索引.md", alias="FOE_CLAUSE_INDEX"
    )
```

In `backend/app/api/dependencies.py`, add:

```python
from app.services.clause_retriever import ClauseRetriever  # 顶部 import 区


@lru_cache(maxsize=1)
def _clause_retriever() -> ClauseRetriever:
    return ClauseRetriever.load(get_settings())


def get_clause_retriever() -> ClauseRetriever:
    """应用级单例：解析 rule_blocks + 标准 markdown 一次，跨请求复用。"""
    return _clause_retriever()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_clause_retriever.py -v`
Expected: PASS (8 passed total)

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/config.py backend/app/api/dependencies.py backend/tests/test_clause_retriever.py
git commit -m "feat(foe): config asset paths + ClauseRetriever singleton"
```

---

## Task 6: 报告端点（生成/轮询/下载）

**Files:**
- Create: `backend/app/api/routes/foe_report.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_foe_report_route.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_foe_report_route.py
import pytest
from fastapi.testclient import TestClient

from app.api.auth_deps import CurrentUser, get_current_user
from app.main import app
from app.models.foe_schemas import ClauseRef


class _FakeRetriever:
    def retrieve(self, obj):
        return [ClauseRef(standard_code="JGJ 80-2016", clause_id="第4.1.1条",
                          official_text="应设置防护栏杆。", source_raw="x")]


@pytest.fixture
def client(monkeypatch):
    # 覆盖认证
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="u1", username="t")
    # 用假检索器，避免读真实标准全文
    import app.api.routes.foe_report as route
    monkeypatch.setattr(route, "get_clause_retriever", lambda: _FakeRetriever())
    yield TestClient(app)
    app.dependency_overrides.clear()


_BODY = {
    "title": "测试",
    "analyses": [{
        "objects": [{
            "related_object": "基坑临边防护", "object_bbox": [0, 0, 1, 1],
            "status": "confirmed_hazard", "hazard_type_id": "missing_protection",
            "hazard_type": "防护缺失", "visual_evidence": "x",
        }]
    }],
}


def test_generate_then_status_then_download(client):
    resp = client.post("/api/foe/report", json=_BODY)
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]

    status = client.get(f"/api/foe/report/status/{task_id}")
    assert status.status_code == 200
    assert status.json()["status"] == "done"  # BackgroundTasks 在测试请求内已执行

    dl = client.get(f"/api/foe/report/download/{task_id}")
    assert dl.status_code == 200
    assert "wordprocessingml" in dl.headers["content-type"]


def test_status_foreign_task_404(client):
    resp = client.post("/api/foe/report", json=_BODY)
    task_id = resp.json()["task_id"]
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="other", username="o")
    assert client.get(f"/api/foe/report/status/{task_id}").status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_foe_report_route.py -v`
Expected: FAIL — 404 on POST (route not registered) / ImportError

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/api/routes/foe_report.py
"""四口五临边条款报告路由（v0.3）。

POST   /api/foe/report             收新 schema 分析 → 起后台任务 → task_id
GET    /api/foe/report/status/{id} 轮询
GET    /api/foe/report/download/{id} 下载 .docx（越权校验）

本期输入来自请求体（微调模型还没接进 analyze_image）。将来分析链产出 FoeAnalysis
后，可直接复用 generate_foe_report_docx 在对话里实时出报告。
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.api.auth_deps import CurrentUser, get_current_user
from app.api.dependencies import get_app_settings, get_clause_retriever
from app.core.config import Settings
from app.models.foe_schemas import FoeAnalysis, FoeReportRequest
from app.services import foe_report_generator as foe

router = APIRouter(prefix="/api/foe/report", tags=["foe-report"])


class GenerateResponse(BaseModel):
    task_id: str


def _run_foe_report(
    task_id: str, analyses_data: list[dict], title: str | None, output_dir: str
) -> None:
    """后台任务体：构造检索器(单例) + 渲染报告，结果写回任务表。"""
    try:
        analyses = [FoeAnalysis.model_validate(a) for a in analyses_data]
        retriever = get_clause_retriever()
        path = foe.generate_foe_report_docx(analyses, retriever, output_dir, title)
        foe.set_task_done(task_id, path)
    except Exception as exc:  # noqa: BLE001 - 失败记录给状态查询
        foe.set_task_error(task_id, str(exc))


@router.post("", response_model=GenerateResponse)
def generate(
    body: FoeReportRequest,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> GenerateResponse:
    task_id = foe.create_task(user.id)
    background_tasks.add_task(
        _run_foe_report,
        task_id,
        [a.model_dump() for a in body.analyses],
        body.title,
        settings.report_dir,
    )
    return GenerateResponse(task_id=task_id)


@router.get("/status/{task_id}")
def status(task_id: str, user: CurrentUser = Depends(get_current_user)) -> dict:
    task = foe.get_task(task_id)
    if task is None or task["user_id"] != user.id:
        raise HTTPException(status_code=404, detail="unknown task_id")
    return task


@router.get("/download/{task_id}")
def download(task_id: str, user: CurrentUser = Depends(get_current_user)) -> FileResponse:
    task = foe.get_task(task_id)
    if task is None or task["user_id"] != user.id:
        raise HTTPException(status_code=404, detail="unknown task_id")
    if task["status"] != "done":
        raise HTTPException(status_code=409, detail=f"report not ready: {task['status']}")
    return FileResponse(
        task["path"],
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"foe_report_{task_id}.docx",
    )
```

In `backend/app/main.py`, register the router (mirror existing includes):

```python
from app.api.routes.foe_report import router as foe_report_router  # import 区
# ... 在其他 include_router 之后：
    app.include_router(foe_report_router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_foe_report_route.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/foe_report.py backend/app/main.py backend/tests/test_foe_report_route.py
git commit -m "feat(foe): /api/foe/report generate/status/download endpoints"
```

---

## Task 7: 全量回归 + 真实样例冒烟

**Files:** 无新增（验证）

- [ ] **Step 1: 跑全部后端测试，确认旧 154 + 新增全绿**

Run: `python -m pytest -q`
Expected: PASS（154 旧 + 新增约 12 个）

- [ ] **Step 2: 真实资产 + 真实样例端到端冒烟（不 mock 检索器）**

Create `backend/tests/test_foe_smoke.py`:

```python
from app.models.foe_schemas import FoeAnalysis
from app.services.clause_retriever import ClauseRetriever
from app.services import foe_report_generator as foe
from app.core.config import get_settings

EXAMPLE = {
    "objects": [{
        "related_object": "基坑临边防护", "object_bbox": [0, 278, 999, 999],
        "status": "confirmed_hazard", "hazard_type_id": "missing_protection",
        "hazard_type": "防护缺失",
        "visual_evidence": "坑边未见连续防护栏杆",
        "rule_basis": "开挖深度2m及以上…未设置防护栏杆…",
        "reasoning_chain": [{"step": "observe", "content": "…"}],
    }]
}


def test_real_assets_produce_report_with_jgj80_clause(tmp_path):
    retriever = ClauseRetriever.load(get_settings())
    analyses = [FoeAnalysis.model_validate(EXAMPLE)]
    path = foe.generate_foe_report_docx(analyses, retriever, str(tmp_path))
    from docx import Document
    full = "\n".join(p.text for p in Document(path).paragraphs)
    # 真实 JGJ 80-2016 第4.1.1条原文应出现在报告中
    assert "防护栏杆" in full
    assert "JGJ 80-2016" in full
```

Run: `python -m pytest tests/test_foe_smoke.py -v`
Expected: PASS（证明确定性映射在真实 rule_blocks+标准全文上命中）

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_foe_smoke.py
git commit -m "test(foe): end-to-end smoke on real KG assets + sample"
```

---

## After Implementation

- 报告功能完成后，按用户要求**对整个 agent 做一次完整审核**（见任务清单 #9）：用
  superpowers:requesting-code-review 或 ce-code-review，覆盖正确性、契约一致性（前后端 schema）、
  安全/越权、新旧 schema 共存、测试充分性。
- 文档同步：在 `docs/architecture.md` 增补 `/api/foe/report` 与 clause_retriever（标注为新 schema 第一块）。
- 标注流水线 spec（`2026-06-16-annotation-feedback-pipeline-integration-design.md`）仍待实现。

## Self-Review（已执行）

- **Spec 覆盖**：新 schema(Task1) · 混合检索 确定性+取原文(Task2-3) · RAG 兜底接口(Task3 semantic_search 注入) · docx 报告(Task4) · 端点三段式(Task6) · 配置(Task5) · 测试(各任务+Task7)。RAG 兜底按 spec"仅兜底"以可注入 hook 实现，本期默认 None（不接网络）。
- **占位符**：无 TODO/TBD；每步含完整代码与命令。
- **类型一致**：`ClauseRetriever.retrieve(FoeObject)->list[ClauseRef]`、`generate_foe_report_docx(analyses, retriever, output_dir, title)`、`foe.create_task/get_task/set_task_done/set_task_error`、`get_clause_retriever()` 在任务间签名一致。
- **下载链接 bug**：FOE 用自己的任务注册表（Task4），`get_task` 返回 `/api/foe/report/download/{id}`，避免复用旧 `report_generator.get_task` 的硬编码路径。
- **偏差记录**：spec 列的 `foe_kg` 配置本期未用（检索只需 rule_blocks+标准+索引），按 YAGNI 未加入 config；如需 KG 增强检索可后续补。

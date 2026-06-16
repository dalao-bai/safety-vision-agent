# backend/tests/test_clause_retriever.py
from app.core.config import get_settings
from app.models.foe_schemas import FoeObject
from app.services.clause_retriever import (
    ClauseRetriever,
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


def test_extract_clause_does_not_match_subclause_prefix():
    # 找 "4.1" 不应误匹配 "4.1.1" 那一条（前缀误匹配回归）
    md = "4.1.1坠落高度基准面应设置防护栏杆。\n4.1.2其他。\n"
    assert extract_clause(md, "4.1") is None


def test_extract_clause_two_level_section_stops_before_subclause():
    md = "4.1 临边作业总则。\n4.1.1坠落高度…\n"
    text = extract_clause(md, "4.1")
    assert text is not None
    assert text.startswith("临边作业总则")
    assert "坠落" not in text


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


def test_load_reads_real_assets():
    """用仓库内真实资产构造检索器，验证默认路径正确、规则已加载。"""
    r = ClauseRetriever.load(get_settings())
    assert r.name2id.get("基坑临边防护") == "foundation_pit_edge_protection"
    assert "JGJ 80-2016" in r.standards

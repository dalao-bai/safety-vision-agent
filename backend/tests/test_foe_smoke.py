# backend/tests/test_foe_smoke.py
"""端到端冒烟：用仓库内真实知识图谱 + 标准全文资产，验证确定性条款命中。

不 mock 检索器；证明 VLM 输出样例经 ClauseRetriever 能命中真实 JGJ 80-2016 条文
并渲染进 .docx。无网络（纯文件解析 + docx）。
"""

from docx import Document

from app.core.config import get_settings
from app.models.foe_schemas import FoeAnalysis
from app.services import foe_report_generator as foe
from app.services.clause_retriever import ClauseRetriever

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
    full = "\n".join(p.text for p in Document(path).paragraphs)
    # 真实 JGJ 80-2016 第4.1.1条原文应出现在报告中
    assert "防护栏杆" in full
    assert "JGJ 80-2016" in full

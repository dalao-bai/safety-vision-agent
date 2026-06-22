from pathlib import Path

from app.persistence.models import Hazard
from app.reports.builder import build_markdown_report


def _hazards():
    return [
        Hazard(id=1, image_id=1, object_id="foundation_pit_edge_protection",
               status="confirmed_hazard", hazard_type_id="missing_protection",
               bbox=[0, 278, 999, 999], reasoning_chain=[], visual_evidence="未见连续防护栏杆",
               rule_basis="开挖深度2m及以上未设置防护栏杆", evidence_sufficiency="sufficient",
               confirmed=True),
    ]


def test_report_contains_sections(tmp_path: Path):
    path = build_markdown_report(
        session_id=7, hazards=_hazards(), report_dir=str(tmp_path),
        object_name_for=lambda oid: "基坑临边防护",
        hazard_name_for=lambda hid: "防护缺失",
        remediation_for=lambda oid: [{"id": "q1", "condition": "设置连续防护栏杆与挡脚板", "source": "JGJ 80-2016 4.1.2"}],
    )
    text = Path(path).read_text(encoding="utf-8")
    assert "# 四口五临边隐患排查报告" in text
    assert "基坑临边防护" in text
    assert "防护缺失" in text
    assert "设置连续防护栏杆与挡脚板" in text
    assert "JGJ 80-2016 4.1.2" in text


def test_empty_report(tmp_path: Path):
    path = build_markdown_report(session_id=1, hazards=[], report_dir=str(tmp_path),
                                 object_name_for=lambda o: o, hazard_name_for=lambda h: h,
                                 remediation_for=lambda o: [])
    assert "未发现已确认隐患" in Path(path).read_text(encoding="utf-8")


def test_newlines_in_text_do_not_inject_headings(tmp_path):
    from pathlib import Path
    from app.persistence.models import Hazard
    from app.reports.builder import build_markdown_report
    hz = [Hazard(id=1, image_id=1, object_id="o", status="confirmed_hazard",
                 hazard_type_id="missing_protection", bbox=[1, 2, 3, 4], reasoning_chain=[],
                 visual_evidence="证据第一行\n## 伪标题\n- 伪列表", rule_basis="r",
                 evidence_sufficiency="sufficient", confirmed=True)]
    path = build_markdown_report(session_id=3, hazards=hz, report_dir=str(tmp_path),
                                 object_name_for=lambda o: "对象\n## 注入", hazard_name_for=lambda h: "防护缺失",
                                 remediation_for=lambda o: [])
    text = Path(path).read_text(encoding="utf-8")
    # the only level-2 headings are the real per-hazard ones (start with "## 1.")
    h2 = [ln for ln in text.splitlines() if ln.startswith("## ")]
    assert all(ln.startswith("## 1.") for ln in h2)
    assert "伪标题" in text  # content preserved, just not as a heading
    assert text.endswith("\n")

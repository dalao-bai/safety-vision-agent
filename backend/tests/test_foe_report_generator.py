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

from app.agent.tools import TOOL_SCHEMAS, dispatch_tool, ToolContext
from app.kg.store import KGStore
from app.persistence.db import Database


class FakeStandards:
    def search(self, query, top_k=3):
        return [{"text": "施工楼梯口安装防护栏杆", "source": "JGJ80.md", "heading": "## 4.1.2"}]


def _ctx(tmp_path, kg_path):
    db = Database(str(tmp_path / "t.db"))
    sid = db.create_session()
    img_id = db.add_image(sid, "p.png", "four_openings_edges")
    db.add_hazards(img_id, [{"object_id": "foundation_pit_edge_protection",
                             "status": "confirmed_hazard", "hazard_type_id": "missing_protection",
                             "bbox": [0, 278, 999, 999], "reasoning_chain": [],
                             "visual_evidence": "e", "rule_basis": "r", "evidence_sufficiency": "sufficient"}])
    ctx = ToolContext(db=db, kg=KGStore.load(str(kg_path)), standards=FakeStandards(),
                      intake=None, report_dir=str(tmp_path / "rep"), session_id=sid)
    return ctx, img_id


def test_schemas_cover_five_tools():
    names = {t["function"]["name"] for t in TOOL_SCHEMAS}
    assert names == {"query_kg", "search_standards", "get_session_hazards",
                     "submit_correction", "export_report"}


def test_query_kg(tmp_path, kg_path):
    ctx, _ = _ctx(tmp_path, kg_path)
    out = dispatch_tool("query_kg", {"object_id": "foundation_pit_edge_protection",
                                     "hazard_type_id": "missing_protection"}, ctx)
    assert out["name"] == "基坑临边防护"
    # foundation_pit has empty qualified_conditions, but rule_blocks ground remediation
    assert out["remediation"] == []
    assert len(out["rule_blocks"]) >= 1
    assert out["rule_blocks"][0]["hazard_type_id"] == "missing_protection"


def test_query_kg_populated_remediation(tmp_path, kg_path):
    ctx, _ = _ctx(tmp_path, kg_path)
    out = dispatch_tool("query_kg", {"object_id": "stair_opening_protection"}, ctx)
    assert len(out["remediation"]) >= 1


def test_search_standards(tmp_path, kg_path):
    ctx, _ = _ctx(tmp_path, kg_path)
    out = dispatch_tool("search_standards", {"query": "楼梯口", "top_k": 1}, ctx)
    assert out["hits"][0]["source"] == "JGJ80.md"


def test_get_session_hazards(tmp_path, kg_path):
    ctx, _ = _ctx(tmp_path, kg_path)
    out = dispatch_tool("get_session_hazards", {}, ctx)
    assert out["hazards"][0]["object_id"] == "foundation_pit_edge_protection"


def test_export_report(tmp_path, kg_path):
    ctx, img_id = _ctx(tmp_path, kg_path)
    ctx.db.mark_hazards_confirmed(img_id)
    out = dispatch_tool("export_report", {}, ctx)
    assert out["report_path"].endswith(".md")


def test_unknown_tool_raises(tmp_path, kg_path):
    ctx, _ = _ctx(tmp_path, kg_path)
    import pytest
    with pytest.raises(ValueError):
        dispatch_tool("nope", {}, ctx)

from app.agent.tools import TOOL_SCHEMAS, ToolGuard, dispatch_tool, ToolContext
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


def test_schemas_cover_all_tools():
    names = {t["function"]["name"] for t in TOOL_SCHEMAS}
    assert names == {"query_kg", "search_standards", "get_session_hazards",
                     "submit_correction", "export_report", "confirm_hazards",
                     "query_statistics", "confirm_hazards_batch"}


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
    assert out["report_path"].endswith(".docx")


def test_unknown_tool_raises(tmp_path, kg_path):
    ctx, _ = _ctx(tmp_path, kg_path)
    import pytest
    with pytest.raises(ValueError):
        dispatch_tool("nope", {}, ctx)


class FakeIntake:
    def __init__(self):
        self.last = None

    def deposit(self, image_path, result, note):
        self.last = (image_path, result, note)
        return "runtime/pipeline_intake"


def test_submit_correction_threads_uncertainty(tmp_path, kg_path):
    from app.kg.store import KGStore
    from app.persistence.db import Database
    db = Database(str(tmp_path / "t.db"))
    sid = db.create_session()
    img_id = db.add_image(sid, "p.png", "four_openings_edges")
    db.add_hazards(img_id, [{"object_id": "foundation_pit_edge_protection", "status": "uncertain",
                             "hazard_type_id": None, "bbox": [1, 2, 3, 4], "reasoning_chain": [],
                             "visual_evidence": "", "rule_basis": "", "evidence_sufficiency": "insufficient",
                             "uncertainty_reason": "protective_component_not_visible",
                             "missing_evidence": "栏杆是否连续被遮挡"}])
    intake = FakeIntake()
    ctx = ToolContext(db=db, kg=KGStore.load(str(kg_path)), standards=FakeStandards(),
                      intake=intake, report_dir=str(tmp_path), session_id=sid)
    out = dispatch_tool("submit_correction", {"image_id": img_id, "note": "不对"}, ctx)
    assert out["ok"] is True
    _, result, note = intake.last
    assert note == "不对"
    assert result.hazards[0].uncertainty_reason == "protective_component_not_visible"
    assert result.hazards[0].missing_evidence == "栏杆是否连续被遮挡"
    assert db.get_image(img_id).status == "corrected_submitted"


def test_submit_correction_empty_hazards_guard(tmp_path, kg_path):
    from app.kg.store import KGStore
    from app.persistence.db import Database
    db = Database(str(tmp_path / "t.db"))
    sid = db.create_session()
    img_id = db.add_image(sid, "p.png", "four_openings_edges")  # no hazards
    ctx = ToolContext(db=db, kg=KGStore.load(str(kg_path)), standards=FakeStandards(),
                      intake=FakeIntake(), report_dir=str(tmp_path), session_id=sid)
    out = dispatch_tool("submit_correction", {"image_id": img_id, "note": "x"}, ctx)
    assert out["ok"] is False


def test_confirm_hazards(tmp_path, kg_path):
    ctx, img_id = _ctx(tmp_path, kg_path)
    out = dispatch_tool("confirm_hazards", {"image_id": img_id}, ctx)
    assert out["ok"] is True
    assert ctx.db.get_hazards(img_id)[0].confirmed is True
    assert ctx.db.get_image(img_id).status == "confirmed"


def test_confirm_hazards_wrong_session(tmp_path, kg_path):
    ctx, _ = _ctx(tmp_path, kg_path)
    other = ctx.db.create_session()
    other_img = ctx.db.add_image(other, "p2.png", "four_openings_edges")
    out = dispatch_tool("confirm_hazards", {"image_id": other_img}, ctx)
    assert out["ok"] is False


def test_submit_correction_wrong_session(tmp_path, kg_path):
    ctx, _ = _ctx(tmp_path, kg_path)
    other = ctx.db.create_session()
    other_img = ctx.db.add_image(other, "p2.png", "four_openings_edges")
    out = dispatch_tool("submit_correction", {"image_id": other_img, "note": "x"}, ctx)
    assert out["ok"] is False


def test_get_session_hazards_without_image_id_truncates(tmp_path, kg_path):
    ctx, img_id = _ctx(tmp_path, kg_path)
    long_text = "X" * 200
    ctx.db.add_hazards(ctx.db.add_image(ctx.session_id, "p2.png", "s"), [
        {"object_id": "stair", "status": "confirmed_hazard", "hazard_type_id": "missing_protection",
         "bbox": None, "reasoning_chain": [], "visual_evidence": long_text,
         "rule_basis": long_text, "evidence_sufficiency": "sufficient"}
    ])
    out = dispatch_tool("get_session_hazards", {}, ctx)
    assert "total" in out and "returned" in out
    for h in out["hazards"]:
        assert len(h["visual_evidence"]) <= 101   # 100 chars + ellipsis
        assert len(h["rule_basis"]) <= 101


def test_get_session_hazards_with_image_id_returns_full(tmp_path, kg_path):
    ctx, img_id = _ctx(tmp_path, kg_path)
    long_text = "X" * 200
    ctx.db.add_hazards(img_id, [
        {"object_id": "pit", "status": "confirmed_hazard", "hazard_type_id": "missing_protection",
         "bbox": None, "reasoning_chain": [], "visual_evidence": long_text,
         "rule_basis": long_text, "evidence_sufficiency": "sufficient"}
    ])
    out = dispatch_tool("get_session_hazards", {"image_id": img_id}, ctx)
    # specific image_id query → full text returned
    hazards_with_long = [h for h in out["hazards"] if len(h["visual_evidence"]) == 200]
    assert len(hazards_with_long) >= 1


def test_get_session_hazards_limit(tmp_path, kg_path):
    db = Database(str(tmp_path / "t.db"))
    sid = db.create_session()
    for i in range(25):
        img_id = db.add_image(sid, f"p{i}.png", "s")
        db.add_hazards(img_id, [{"object_id": "o", "status": "confirmed_hazard",
                                  "hazard_type_id": "missing_protection", "bbox": None,
                                  "reasoning_chain": [], "visual_evidence": "", "rule_basis": "",
                                  "evidence_sufficiency": "sufficient"}])
    from app.kg.store import KGStore
    ctx = ToolContext(db=db, kg=KGStore.load(str(kg_path)), standards=FakeStandards(),
                      intake=None, report_dir=str(tmp_path), session_id=sid)
    out = dispatch_tool("get_session_hazards", {}, ctx)
    assert out["total"] == 25
    assert out["returned"] == 20
    assert len(out["hazards"]) == 20

    out2 = dispatch_tool("get_session_hazards", {"limit": 5}, ctx)
    assert out2["returned"] == 5


def test_query_kg_rule_blocks_capped(tmp_path, kg_path):
    ctx, _ = _ctx(tmp_path, kg_path)
    out = dispatch_tool("query_kg", {"object_id": "foundation_pit_edge_protection"}, ctx)
    assert len(out["rule_blocks"]) <= 5
    assert "rule_blocks_total" in out
    assert out["rule_blocks_total"] >= len(out["rule_blocks"])
    for b in out["rule_blocks"]:
        assert len(b["rule_text"]) <= 201   # 200 chars + ellipsis


# --- ToolGuard unit tests ---

def test_guard_unknown_tool():
    g = ToolGuard()
    err = g.check("nonexistent_tool", {})
    assert err is not None
    assert "未知工具" in err
    assert "nonexistent_tool" in err


def test_guard_missing_required_param():
    g = ToolGuard()
    err = g.check("search_standards", {})   # query is required
    assert err is not None
    assert "query" in err


def test_guard_missing_required_param_none_value():
    g = ToolGuard()
    err = g.check("search_standards", {"query": None})
    assert err is not None
    assert "query" in err


def test_guard_allows_no_required_params():
    g = ToolGuard()
    assert g.check("export_report", {}) is None


def test_guard_duplicate_call_blocked():
    g = ToolGuard()
    assert g.check("search_standards", {"query": "基坑"}) is None
    err = g.check("search_standards", {"query": "基坑"})
    assert err is not None
    assert "重复" in err


def test_guard_different_args_allowed():
    g = ToolGuard()
    assert g.check("search_standards", {"query": "基坑"}) is None
    assert g.check("search_standards", {"query": "楼梯"}) is None


def test_guard_resets_per_instance():
    g1 = ToolGuard()
    g2 = ToolGuard()
    g1.check("export_report", {})
    assert g2.check("export_report", {}) is None  # separate instance, not blocked


def test_query_statistics_tool(tmp_path, kg_path):
    ctx, img_id = _ctx(tmp_path, kg_path)
    sid2 = ctx.db.create_session()
    img2 = ctx.db.add_image(sid2, "p2.png", "four_openings_edges")
    ctx.db.add_hazards(img2, [{"object_id": "stair_opening_protection", "status": "confirmed_hazard",
                               "hazard_type_id": "discontinuous_protection", "bbox": None,
                               "reasoning_chain": [], "visual_evidence": "", "rule_basis": "",
                               "evidence_sufficiency": "sufficient"}])
    ctx.db.mark_hazards_confirmed(img_id)
    ctx.db.mark_hazards_confirmed(img2)

    out = dispatch_tool("query_statistics", {}, ctx)
    assert out["total"] == 2
    assert out["confirmed_only"] is True

    out2 = dispatch_tool("query_statistics", {"hazard_type_id": "missing_protection"}, ctx)
    assert out2["total"] == 1
    assert out2["breakdown"][0]["hazard_type_id"] == "missing_protection"

    out3 = dispatch_tool("query_statistics", {"confirmed_only": False}, ctx)
    assert out3["total"] == 2


def test_confirm_hazards_batch_by_ids(tmp_path, kg_path):
    ctx, img_id = _ctx(tmp_path, kg_path)
    out = dispatch_tool("confirm_hazards_batch", {"image_ids": [img_id]}, ctx)
    assert out["ok"] is True
    assert out["confirmed_count"] == 1
    assert img_id in out["image_ids"]
    assert ctx.db.get_image(img_id).status == "confirmed"
    assert ctx.db.get_hazards(img_id)[0].confirmed is True


def test_confirm_hazards_batch_confirm_all(tmp_path, kg_path):
    ctx, img_id = _ctx(tmp_path, kg_path)
    img2 = ctx.db.add_image(ctx.session_id, "p2.png", "s")
    ctx.db.add_hazards(img2, [{"object_id": "foundation_pit_edge_protection",
                               "status": "confirmed_hazard", "hazard_type_id": "missing_protection",
                               "bbox": [1, 2, 3, 4], "reasoning_chain": [],
                               "visual_evidence": "e", "rule_basis": "r",
                               "evidence_sufficiency": "sufficient"}])
    out = dispatch_tool("confirm_hazards_batch", {"confirm_all": True}, ctx)
    assert out["confirmed_count"] == 2
    assert sorted(out["image_ids"]) == sorted([img_id, img2])


def test_confirm_hazards_batch_cross_session_blocked(tmp_path, kg_path):
    ctx, _ = _ctx(tmp_path, kg_path)
    other_sid = ctx.db.create_session()
    other_img = ctx.db.add_image(other_sid, "other.png", "s")
    out = dispatch_tool("confirm_hazards_batch", {"image_ids": [other_img]}, ctx)
    assert other_img not in out["image_ids"]
    assert out["confirmed_count"] == 0


def test_confirm_hazards_batch_no_args(tmp_path, kg_path):
    ctx, img_id = _ctx(tmp_path, kg_path)
    out = dispatch_tool("confirm_hazards_batch", {}, ctx)
    assert out["ok"] is True
    assert out["confirmed_count"] == 0
    assert out["image_ids"] == []
    assert ctx.db.get_image(img_id).status == "awaiting_confirmation"


def test_get_session_hazards_status_filter(tmp_path, kg_path):
    ctx, img_id = _ctx(tmp_path, kg_path)
    ctx.db.add_hazards(img_id, [{"object_id": "stair_opening_protection",
                                 "status": "uncertain", "hazard_type_id": None,
                                 "bbox": None, "reasoning_chain": [],
                                 "visual_evidence": "e", "rule_basis": "r",
                                 "evidence_sufficiency": "insufficient"}])
    out_confirmed = dispatch_tool("get_session_hazards", {"status_filter": "confirmed_hazard"}, ctx)
    assert all(h["status"] == "confirmed_hazard" for h in out_confirmed["hazards"])
    out_uncertain = dispatch_tool("get_session_hazards", {"status_filter": "uncertain"}, ctx)
    assert all(h["status"] == "uncertain" for h in out_uncertain["hazards"])

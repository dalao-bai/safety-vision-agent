from pathlib import Path

from app.persistence.db import Database


def test_session_message_roundtrip(tmp_path: Path):
    db = Database(str(tmp_path / "t.db"))
    sid = db.create_session()
    db.add_message(sid, "user", "你好")
    msgs = db.get_messages(sid)
    assert [m.role for m in msgs] == ["user"]
    assert msgs[0].content == "你好"


def test_image_and_hazards(tmp_path: Path):
    db = Database(str(tmp_path / "t.db"))
    sid = db.create_session()
    img_id = db.add_image(sid, path="runtime/uploads/x.png", scene="four_openings_edges")
    db.add_hazards(img_id, [
        {"object_id": "foundation_pit_edge_protection", "status": "confirmed_hazard",
         "hazard_type_id": "missing_protection", "bbox": [0, 278, 999, 999],
         "reasoning_chain": [{"step": "observe", "content": "x"}],
         "visual_evidence": "ev", "rule_basis": "rb", "evidence_sufficiency": "sufficient"},
    ])
    assert db.get_image(img_id).status == "awaiting_confirmation"
    hz = db.get_hazards(img_id)
    assert len(hz) == 1 and hz[0].bbox == [0, 278, 999, 999]
    assert hz[0].confirmed is False


def test_confirm_and_correction(tmp_path: Path):
    db = Database(str(tmp_path / "t.db"))
    sid = db.create_session()
    img_id = db.add_image(sid, path="p.png", scene="s")
    db.add_hazards(img_id, [{"object_id": "o", "status": "confirmed_hazard",
                             "hazard_type_id": "missing_protection", "bbox": [1, 2, 3, 4],
                             "reasoning_chain": [], "visual_evidence": "", "rule_basis": "",
                             "evidence_sufficiency": "sufficient"}])
    db.set_image_status(img_id, "confirmed")
    db.mark_hazards_confirmed(img_id)
    assert db.get_image(img_id).status == "confirmed"
    assert db.get_hazards(img_id)[0].confirmed is True

    db.add_correction(img_id, note="bbox 偏了", intake_path="runtime/pipeline_intake/images/foe_000001.png")
    cs = db.get_corrections(img_id)
    assert cs[0].note == "bbox 偏了"


def test_confirmed_hazards_for_session(tmp_path: Path):
    db = Database(str(tmp_path / "t.db"))
    sid = db.create_session()
    img_id = db.add_image(sid, path="p.png", scene="s")
    db.add_hazards(img_id, [{"object_id": "o", "status": "confirmed_hazard",
                             "hazard_type_id": "missing_protection", "bbox": [1, 2, 3, 4],
                             "reasoning_chain": [], "visual_evidence": "e", "rule_basis": "r",
                             "evidence_sufficiency": "sufficient"}])
    db.mark_hazards_confirmed(img_id)
    rows = db.get_confirmed_hazards(sid)
    assert len(rows) == 1 and rows[0].object_id == "o"


def test_get_image_missing_raises(tmp_path: Path):
    import pytest
    db = Database(str(tmp_path / "t.db"))
    with pytest.raises(KeyError):
        db.get_image(999)


def test_reasoning_chain_none_normalizes_to_list(tmp_path: Path):
    db = Database(str(tmp_path / "t.db"))
    sid = db.create_session()
    img_id = db.add_image(sid, "p.png", "s")
    db.add_hazards(img_id, [{"object_id": "o", "status": "confirmed_hazard",
                             "hazard_type_id": "missing_protection", "bbox": None,
                             "reasoning_chain": None, "visual_evidence": "", "rule_basis": "",
                             "evidence_sufficiency": "sufficient"}])
    h = db.get_hazards(img_id)[0]
    assert h.reasoning_chain == []
    assert h.bbox is None


def test_hazard_uncertainty_fields_roundtrip(tmp_path):
    from app.persistence.db import Database
    db = Database(str(tmp_path / "t.db"))
    sid = db.create_session()
    img_id = db.add_image(sid, "p.png", "s")
    db.add_hazards(img_id, [{"object_id": "o", "status": "uncertain",
                             "hazard_type_id": None, "bbox": [1, 2, 3, 4], "reasoning_chain": [],
                             "visual_evidence": "", "rule_basis": "", "evidence_sufficiency": "insufficient",
                             "uncertainty_reason": "protective_component_not_visible",
                             "missing_evidence": "栏杆是否连续被遮挡"}])
    h = db.get_hazards(img_id)[0]
    assert h.uncertainty_reason == "protective_component_not_visible"
    assert h.missing_evidence == "栏杆是否连续被遮挡"


def test_hazard_uncertainty_fields_default_none(tmp_path):
    from app.persistence.db import Database
    db = Database(str(tmp_path / "t.db"))
    sid = db.create_session()
    img_id = db.add_image(sid, "p.png", "s")
    db.add_hazards(img_id, [{"object_id": "o", "status": "confirmed_hazard",
                             "hazard_type_id": "missing_protection", "bbox": [1, 2, 3, 4],
                             "reasoning_chain": [], "visual_evidence": "", "rule_basis": "",
                             "evidence_sufficiency": "sufficient"}])
    h = db.get_hazards(img_id)[0]
    assert h.uncertainty_reason is None and h.missing_evidence is None


_BASE_HAZARD = {"bbox": None, "reasoning_chain": [], "visual_evidence": "", "rule_basis": "", "evidence_sufficiency": "sufficient"}


def test_query_hazard_stats_basic(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    sid = db.create_session()
    img_id = db.add_image(sid, "p.png", "s")
    db.add_hazards(img_id, [
        {**_BASE_HAZARD, "object_id": "pit", "status": "confirmed_hazard", "hazard_type_id": "missing_protection"},
        {**_BASE_HAZARD, "object_id": "pit", "status": "confirmed_hazard", "hazard_type_id": "missing_protection"},
        {**_BASE_HAZARD, "object_id": "stair", "status": "confirmed_hazard", "hazard_type_id": "discontinuous_protection"},
    ])
    db.mark_hazards_confirmed(img_id)
    stats = db.query_hazard_stats()
    assert stats["total"] == 3
    assert stats["breakdown"][0]["count"] == 2
    assert stats["breakdown"][0]["hazard_type_id"] == "missing_protection"
    assert stats["breakdown"][1]["count"] == 1


def test_query_hazard_stats_confirmed_only_false(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    sid = db.create_session()
    img_id = db.add_image(sid, "p.png", "s")
    db.add_hazards(img_id, [
        {**_BASE_HAZARD, "object_id": "pit", "status": "confirmed_hazard", "hazard_type_id": "missing_protection"},
        {**_BASE_HAZARD, "object_id": "pit", "status": "uncertain", "hazard_type_id": None},
    ])
    assert db.query_hazard_stats(confirmed_only=True)["total"] == 1
    assert db.query_hazard_stats(confirmed_only=False)["total"] == 2


def test_query_hazard_stats_date_filter(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    sid = db.create_session()
    old_img = db.add_image(sid, "old.png", "s", _created_at="2026-05-01T00:00:00Z")
    new_img = db.add_image(sid, "new.png", "s", _created_at="2026-06-15T00:00:00Z")
    for img_id in (old_img, new_img):
        db.add_hazards(img_id, [{**_BASE_HAZARD, "object_id": "pit", "status": "confirmed_hazard", "hazard_type_id": "missing_protection"}])
        db.mark_hazards_confirmed(img_id)
    assert db.query_hazard_stats()["total"] == 2
    assert db.query_hazard_stats(date_from="2026-06-01")["total"] == 1
    assert db.query_hazard_stats(date_to="2026-05-31")["total"] == 1
    assert db.query_hazard_stats(date_from="2026-06-01", date_to="2026-06-30")["total"] == 1
    assert db.query_hazard_stats(date_from="2026-07-01")["total"] == 0


def test_query_hazard_stats_hazard_type_filter(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    sid = db.create_session()
    img_id = db.add_image(sid, "p.png", "s")
    db.add_hazards(img_id, [
        {**_BASE_HAZARD, "object_id": "pit", "status": "confirmed_hazard", "hazard_type_id": "missing_protection"},
        {**_BASE_HAZARD, "object_id": "stair", "status": "confirmed_hazard", "hazard_type_id": "discontinuous_protection"},
    ])
    db.mark_hazards_confirmed(img_id)
    stats = db.query_hazard_stats(hazard_type_id="missing_protection")
    assert stats["total"] == 1
    assert stats["breakdown"][0]["hazard_type_id"] == "missing_protection"


def test_query_hazard_stats_empty(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    stats = db.query_hazard_stats()
    assert stats["total"] == 0
    assert stats["breakdown"] == []


def test_get_pending_image_ids(tmp_path: Path):
    db = Database(str(tmp_path / "t.db"))
    sid = db.create_session()
    img1 = db.add_image(sid, "p1.png", "s")
    img2 = db.add_image(sid, "p2.png", "s")
    img3 = db.add_image(sid, "p3.png", "s")
    db.set_image_status(img2, "confirmed")

    pending = db.get_pending_image_ids(sid)
    assert sorted(pending) == sorted([img1, img3])

    # cross-session isolation
    sid2 = db.create_session()
    img4 = db.add_image(sid2, "p4.png", "s")
    assert img4 not in db.get_pending_image_ids(sid)


def test_tool_trace_roundtrip(tmp_path: Path):
    db = Database(str(tmp_path / "t.db"))
    sid = db.create_session()
    msg_id = db.add_message(sid, "user", "hi")

    trace_id = db.add_tool_trace(
        session_id=sid, turn_user_msg_id=msg_id, iteration=0,
        tool_name="search_standards", args_json='{"query": "基坑"}',
        result_summary="hits:1", duration_ms=12.5, outcome="ok",
    )
    assert trace_id > 0

    traces = db.get_tool_traces(sid)
    assert len(traces) == 1
    t = traces[0]
    assert t.tool_name == "search_standards"
    assert t.outcome == "ok"
    assert t.loop_outcome == "pending"
    assert t.duration_ms == 12.5
    assert t.args_json == '{"query": "基坑"}'


def test_tool_trace_flush(tmp_path: Path):
    db = Database(str(tmp_path / "t.db"))
    sid = db.create_session()
    msg_id = db.add_message(sid, "user", "hi")

    db.add_tool_trace(sid, msg_id, 0, "query_kg", "{}", "result", 5.0, "ok")
    db.add_tool_trace(sid, msg_id, 1, "finish", "{}", "done", 2.0, "ok")

    db.flush_tool_traces(sid, "finish")

    traces = db.get_tool_traces(sid)
    assert all(t.loop_outcome == "finish" for t in traces)


def test_tool_trace_flush_cross_session_isolation(tmp_path: Path):
    db = Database(str(tmp_path / "t.db"))
    sid1 = db.create_session()
    sid2 = db.create_session()
    m1 = db.add_message(sid1, "user", "a")
    m2 = db.add_message(sid2, "user", "b")

    db.add_tool_trace(sid1, m1, 0, "query_kg", "{}", "r", 1.0, "ok")
    db.add_tool_trace(sid2, m2, 0, "query_kg", "{}", "r", 1.0, "ok")

    db.flush_tool_traces(sid1, "no_tool_calls")

    assert db.get_tool_traces(sid1)[0].loop_outcome == "no_tool_calls"
    assert db.get_tool_traces(sid2)[0].loop_outcome == "pending"

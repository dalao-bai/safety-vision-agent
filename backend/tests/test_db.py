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

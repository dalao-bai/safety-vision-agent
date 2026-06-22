import json
import sys
from pathlib import Path

from app.correction.intake import IntakeWriter
from app.vlm.detector import DetectionResult, Hazard


def _result() -> DetectionResult:
    return DetectionResult(scene="four_openings_edges", hazards=[
        Hazard(object_id="foundation_pit_edge_protection", object_name="基坑临边防护",
               status="confirmed_hazard", hazard_type_id="missing_protection", hazard_type="防护缺失",
               bbox=[0, 278, 999, 999], visual_evidence="ev", rule_basis="rb",
               evidence_sufficiency="sufficient", uncertainty_reason=None,
               reasoning_chain=[{"step": "observe", "content": "x"}]),
    ])


def test_deposit_layout(tiny_png, tmp_path: Path):
    w = IntakeWriter(intake_dir=str(tmp_path / "intake"))
    path = w.deposit(image_path=str(tiny_png), result=_result(), note="基坑那个框偏大了")
    intake = Path(path)
    images = intake / "images"
    pngs = list(images.glob("*.png"))
    paired = list(images.glob("*.json"))
    corr = list((intake / "corrections").glob("*.correction.json"))
    assert len(pngs) == 1 and len(paired) == 1 and len(corr) == 1

    doc = json.loads(paired[0].read_text(encoding="utf-8"))
    assert doc["agent_correction_note"] == "基坑那个框偏大了"
    assert doc["objects"][0]["object_id"] == "foundation_pit_edge_protection"
    assert doc["objects"][0]["bbox"] == [0, 278, 999, 999]

    note = json.loads(corr[0].read_text(encoding="utf-8"))
    assert note["note"] == "基坑那个框偏大了"


def test_paired_json_accepted_by_pipeline_normalize(tiny_png, tmp_path: Path, repo_root: Path):
    """The paired objects must normalize without crashing in annotation_pipeline."""
    w = IntakeWriter(intake_dir=str(tmp_path / "intake"))
    w.deposit(image_path=str(tiny_png), result=_result(), note="x")
    paired = next((tmp_path / "intake" / "images").glob("*.json"))
    parsed = json.loads(paired.read_text(encoding="utf-8"))

    sys.path.insert(0, str(repo_root))
    from annotation_pipeline.normalize import normalize_draft
    from annotation_pipeline.rules import RuleStore
    rules = RuleStore.load(repo_root / "知识图谱主文件" / "four_openings_edges_rule_blocks.json")
    img = next((tmp_path / "intake" / "images").glob("*.png"))
    draft = normalize_draft(parsed, img, 1000, 1000, rules, "mock", True)
    assert draft["objects"][0]["object_id"] == "foundation_pit_edge_protection"
    assert draft["objects"][0]["bbox"] == [0, 278, 999, 999]


def test_paired_json_includes_scene(tiny_png, tmp_path):
    w = IntakeWriter(intake_dir=str(tmp_path / "intake"))
    w.deposit(image_path=str(tiny_png), result=_result(), note="x")
    import json as _json
    paired = next((tmp_path / "intake" / "images").glob("*.json"))
    assert _json.loads(paired.read_text(encoding="utf-8"))["scene"] == "four_openings_edges"


def test_double_deposit_preserves_both(tiny_png, tmp_path):
    w = IntakeWriter(intake_dir=str(tmp_path / "intake"))
    w.deposit(image_path=str(tiny_png), result=_result(), note="第一次纠错")
    w.deposit(image_path=str(tiny_png), result=_result(), note="第二次纠错")
    import json as _json
    corr = sorted((tmp_path / "intake" / "corrections").glob("*.correction.json"))
    assert len(corr) == 2
    notes = {_json.loads(p.read_text(encoding="utf-8"))["note"] for p in corr}
    assert notes == {"第一次纠错", "第二次纠错"}
    # paired drafts also both present
    assert len(list((tmp_path / "intake" / "images").glob("*.json"))) == 2

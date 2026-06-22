import json
from types import SimpleNamespace

from app.agent.orchestrator import Orchestrator
from app.agent.tools import ToolContext
from app.kg.store import KGStore
from app.persistence.db import Database


class ScriptedAgent:
    """Returns queued responses; each is (content, tool_calls list of (name, args dict))."""
    def __init__(self, script):
        self._script = list(script)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        content, tool_calls = self._script.pop(0)
        tc_objs = []
        for i, (name, arguments) in enumerate(tool_calls):
            tc_objs.append(SimpleNamespace(id=f"c{i}", type="function",
                function=SimpleNamespace(name=name, arguments=json.dumps(arguments))))
        msg = SimpleNamespace(content=content, tool_calls=tc_objs or None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


class FakeStandards:
    def search(self, query, top_k=3):
        return [{"text": "基坑周边设置防护栏杆与挡脚板", "source": "JGJ59.md", "heading": "## B.13"}]


class FakeIntake:
    def __init__(self): self.calls = []
    def deposit(self, image_path, result, note):
        self.calls.append(note)
        return "runtime/pipeline_intake"


def _orch(tmp_path, kg_path, script):
    db = Database(str(tmp_path / "t.db"))
    kg = KGStore.load(str(kg_path))
    intake = FakeIntake()

    def ctx_factory(session_id):
        return ToolContext(db=db, kg=kg, standards=FakeStandards(), intake=intake,
                           report_dir=str(tmp_path / "rep"), session_id=session_id)

    orch = Orchestrator(db=db, agent_client=ScriptedAgent(script), agent_model="agent-x",
                        ctx_factory=ctx_factory, max_iterations=5)
    return orch, db, intake


def test_qa_with_tool_then_answer(tmp_path, kg_path):
    script = [
        ("", [("search_standards", {"query": "基坑 防护"})]),
        ("基坑周边应设置防护栏杆与挡脚板(JGJ59 B.13)。", []),
    ]
    orch, db, _ = _orch(tmp_path, kg_path, script)
    sid = db.create_session()
    reply = orch.handle_message(sid, "基坑临边怎么防护?")
    assert "挡脚板" in reply
    assert [m.role for m in db.get_messages(sid)][-2:] == ["user", "assistant"]


def test_correction_flow_calls_intake(tmp_path, kg_path):
    db = Database(str(tmp_path / "t.db"))
    sid = db.create_session()
    img_id = db.add_image(sid, "p.png", "four_openings_edges")
    db.add_hazards(img_id, [{"object_id": "foundation_pit_edge_protection", "status": "confirmed_hazard",
                             "hazard_type_id": "missing_protection", "bbox": [0, 278, 999, 999],
                             "reasoning_chain": [], "visual_evidence": "e", "rule_basis": "r",
                             "evidence_sufficiency": "sufficient"}])
    script = [
        ("", [("submit_correction", {"image_id": img_id, "note": "框偏大了"})]),
        ("已记录你的纠错并送入标注流水线。", []),
    ]
    kg = KGStore.load(str(kg_path))
    intake = FakeIntake()
    orch = Orchestrator(db=db, agent_client=ScriptedAgent(script), agent_model="agent-x",
                        ctx_factory=lambda s: ToolContext(db=db, kg=kg, standards=FakeStandards(),
                                                          intake=intake, report_dir=str(tmp_path), session_id=s),
                        max_iterations=5)
    reply = orch.handle_message(sid, "不对,基坑那个框偏大了")
    assert "流水线" in reply
    assert intake.calls == ["框偏大了"]
    assert db.get_image(img_id).status == "corrected_submitted"


def test_loop_stops_at_max_iterations(tmp_path, kg_path):
    script = [("", [("search_standards", {"query": "x"})])] * 10
    orch, db, _ = _orch(tmp_path, kg_path, script)
    sid = db.create_session()
    reply = orch.handle_message(sid, "loop?")
    assert "尝试" in reply


def test_handle_image_persists_and_presents(tmp_path, kg_path):
    from app.vlm.detector import DetectionResult, Hazard
    orch, db, _ = _orch(tmp_path, kg_path, [])
    sid = db.create_session()
    result = DetectionResult(scene="four_openings_edges", hazards=[
        Hazard(object_id="foundation_pit_edge_protection", object_name="基坑临边防护",
               status="uncertain", hazard_type_id=None, hazard_type=None, bbox=[1, 2, 3, 4],
               visual_evidence="ev", rule_basis="", evidence_sufficiency="insufficient",
               uncertainty_reason="protective_component_not_visible", reasoning_chain=[],
               missing_evidence="栏杆是否被遮挡")])
    img_id = orch.handle_image(sid, "p.png", result)
    hz = db.get_hazards(img_id)
    assert hz[0].uncertainty_reason == "protective_component_not_visible"
    assert hz[0].missing_evidence == "栏杆是否被遮挡"
    # the presentation/confirmation message was stored as an assistant message
    assert any("是否正确" in m.content for m in db.get_messages(sid) if m.role == "assistant")


def test_build_messages_single_leading_system(tmp_path, kg_path):
    from app.vlm.detector import DetectionResult, Hazard
    orch, db, _ = _orch(tmp_path, kg_path, [])
    sid = db.create_session()
    result = DetectionResult(scene="four_openings_edges", hazards=[
        Hazard(object_id="foundation_pit_edge_protection", object_name="基坑临边防护",
               status="confirmed_hazard", hazard_type_id="missing_protection", hazard_type="防护缺失",
               bbox=[1, 2, 3, 4], visual_evidence="ev", rule_basis="", evidence_sufficiency="sufficient",
               uncertainty_reason=None, reasoning_chain=[], missing_evidence=None)])
    img_id = orch.handle_image(sid, "p.png", result)
    db.add_message(sid, "user", "hi")
    msgs = orch._build_messages(sid)
    system_msgs = [m for m in msgs if m["role"] == "system"]
    assert len(system_msgs) == 1
    assert msgs[0]["role"] == "system"
    assert f"image_id={img_id}" in msgs[0]["content"]  # context hoisted into leading system block

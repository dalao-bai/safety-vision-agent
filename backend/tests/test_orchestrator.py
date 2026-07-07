import json
from types import SimpleNamespace

from app.agent.orchestrator import Orchestrator, ingest_image, ingest_batch_images
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
    img_id = ingest_image(db, sid, "p.png", result)
    hz = db.get_hazards(img_id)
    assert hz[0].uncertainty_reason == "protective_component_not_visible"
    assert hz[0].missing_evidence == "栏杆是否被遮挡"
    # the presentation/confirmation message was stored as an assistant message
    assert any("是否正确" in m.content for m in db.get_messages(sid) if m.role == "assistant")


def _sample_result():
    from app.vlm.detector import DetectionResult, Hazard
    return DetectionResult(scene="four_openings_edges", hazards=[
        Hazard(object_id="foundation_pit_edge_protection", object_name="基坑临边防护",
               status="confirmed_hazard", hazard_type_id="missing_protection", hazard_type="防护缺失",
               bbox=[1, 2, 3, 4], visual_evidence="ev", rule_basis="", evidence_sufficiency="sufficient",
               uncertainty_reason=None, reasoning_chain=[], missing_evidence=None)])


def test_completed_image_detection_summary_compressed(tmp_path, kg_path):
    orch, db, _ = _orch(tmp_path, kg_path, [])
    sid = db.create_session()
    img_id = ingest_image(db, sid, "p.png", _sample_result())
    # confirm the image → terminal state
    db.mark_hazards_confirmed(img_id)
    db.set_image_status(img_id, "confirmed")

    msgs = orch._build_messages(sid)
    asst_contents = [m["content"] for m in msgs if m["role"] == "assistant"]
    assert len(asst_contents) == 1
    # compressed to one-liner, not the full detection dump
    assert "是否正确" not in asst_contents[0]
    assert "已确认" in asst_contents[0]
    assert str(img_id) in asst_contents[0]
    # system ctx also compressed
    sys_content = msgs[0]["content"]
    assert "待确认图片" not in sys_content
    assert "[已处理]" in sys_content


def test_pending_image_detection_summary_kept(tmp_path, kg_path):
    orch, db, _ = _orch(tmp_path, kg_path, [])
    sid = db.create_session()
    ingest_image(db, sid, "p.png", _sample_result())

    msgs = orch._build_messages(sid)
    asst_contents = [m["content"] for m in msgs if m["role"] == "assistant"]
    assert "是否正确" in asst_contents[0]
    assert "待确认图片" in msgs[0]["content"]


def test_mixed_images_compress_only_completed(tmp_path, kg_path):
    orch, db, _ = _orch(tmp_path, kg_path, [])
    sid = db.create_session()
    img1 = ingest_image(db, sid, "p1.png", _sample_result())
    img2 = ingest_image(db, sid, "p2.png", _sample_result())
    db.mark_hazards_confirmed(img1)
    db.set_image_status(img1, "confirmed")
    # img2 remains awaiting_confirmation

    msgs = orch._build_messages(sid)
    asst_contents = [m["content"] for m in msgs if m["role"] == "assistant"]
    assert len(asst_contents) == 2
    assert "已确认" in asst_contents[0]        # img1 compressed
    assert "是否正确" in asst_contents[1]       # img2 kept intact
    sys_content = msgs[0]["content"]
    assert "[已处理]" in sys_content            # img1 ctx compressed
    assert "待确认图片" in sys_content           # img2 ctx kept


def test_guard_unknown_tool_via_orchestrator(tmp_path, kg_path):
    # Model emits a hallucinated tool name; guard rejects it and feeds error
    # back as tool result; model then produces a text reply.
    script = [
        ("", [("ghost_tool", {"x": 1})]),
        ("抱歉，该工具不存在。", []),
    ]
    orch, db, _ = _orch(tmp_path, kg_path, script)
    sid = db.create_session()
    reply = orch.handle_message(sid, "随便问点啥")
    assert "抱歉" in reply   # loop completed normally


def test_guard_duplicate_tool_via_orchestrator(tmp_path, kg_path):
    # Model sends the same tool call twice; second is blocked by guard; model
    # receives error and produces a text answer without hitting max_iterations.
    script = [
        ("", [("search_standards", {"query": "基坑"})]),
        ("", [("search_standards", {"query": "基坑"})]),   # duplicate → blocked
        ("已查到相关标准。", []),
    ]
    orch, db, _ = _orch(tmp_path, kg_path, script)
    sid = db.create_session()
    reply = orch.handle_message(sid, "基坑防护标准?")
    assert "已查到" in reply


def test_handle_batch_images_success(tmp_path, kg_path):
    orch, db, _ = _orch(tmp_path, kg_path, [])
    sid = db.create_session()
    succeeded = [("p1.png", _sample_result()), ("p2.png", _sample_result())]

    result = ingest_batch_images(db, sid, succeeded, failed_files=[])

    assert result["succeeded"] == 2
    assert result["failed"] == 0
    assert result["total"] == 2
    assert result["summary"]["confirmed_hazard"] == 2
    assert "已完成 2 张图识别" in result["assistant_message"]

    msgs = db.get_messages(sid)
    assert [m.role for m in msgs] == ["assistant", "system"]
    assert msgs[1].content.startswith("[context] 批量上传 image_ids=")


def test_handle_batch_images_partial_failure(tmp_path, kg_path):
    orch, db, _ = _orch(tmp_path, kg_path, [])
    sid = db.create_session()

    result = ingest_batch_images(
        db, sid,
        succeeded=[("p1.png", _sample_result())],
        failed_files=[{"filename": "p2.png", "reason": "vlm_error"}],
    )

    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert result["total"] == 2
    msgs = db.get_messages(sid)
    assert any(m.content.startswith("[context] 批量上传 image_ids=") for m in msgs)
    assert "失败" in result["assistant_message"]


def test_handle_batch_images_all_failed(tmp_path, kg_path):
    orch, db, _ = _orch(tmp_path, kg_path, [])
    sid = db.create_session()

    result = ingest_batch_images(
        db, sid,
        succeeded=[],
        failed_files=[
            {"filename": "p1.png", "reason": "vlm_error"},
            {"filename": "p2.png", "reason": "vlm_error"},
        ],
    )

    assert result["succeeded"] == 0
    assert result["failed"] == 2
    assert result["total"] == 2
    msgs = db.get_messages(sid)
    assert len(msgs) == 1
    assert msgs[0].role == "assistant"
    assert "失败" in msgs[0].content
    assert not any(m.content.startswith("[context] 批量上传 image_ids=") for m in msgs)


def test_build_messages_batch_compression(tmp_path, kg_path):
    orch, db, _ = _orch(tmp_path, kg_path, [])
    sid = db.create_session()
    ingest_batch_images(db, sid, [("p1.png", _sample_result()), ("p2.png", _sample_result())],
                        failed_files=[])
    ctx_msg = next(m for m in db.get_messages(sid)
                   if m.content.startswith("[context] 批量上传 image_ids="))
    img_ids = [int(x) for x in ctx_msg.content.split("=")[1].split(",")]

    # before confirmation: full summary visible
    built = orch._build_messages(sid)
    assert any("已完成" in m["content"] for m in built if m["role"] == "assistant")

    for img_id in img_ids:
        db.mark_hazards_confirmed(img_id)
        db.set_image_status(img_id, "confirmed")

    # after confirmation: summary compressed
    built2 = orch._build_messages(sid)
    asst = [m["content"] for m in built2 if m["role"] == "assistant"]
    assert any("[批量已处理]" in c for c in asst)
    assert not any("已完成" in c for c in asst)
    sys_content = built2[0]["content"]
    assert "[已处理] 批量上传" in sys_content
    assert "[context] 批量上传 image_ids=" not in sys_content


def test_build_messages_single_leading_system(tmp_path, kg_path):
    from app.vlm.detector import DetectionResult, Hazard
    orch, db, _ = _orch(tmp_path, kg_path, [])
    sid = db.create_session()
    result = DetectionResult(scene="four_openings_edges", hazards=[
        Hazard(object_id="foundation_pit_edge_protection", object_name="基坑临边防护",
               status="confirmed_hazard", hazard_type_id="missing_protection", hazard_type="防护缺失",
               bbox=[1, 2, 3, 4], visual_evidence="ev", rule_basis="", evidence_sufficiency="sufficient",
               uncertainty_reason=None, reasoning_chain=[], missing_evidence=None)])
    img_id = ingest_image(db, sid, "p.png", result)
    db.add_message(sid, "user", "hi")
    msgs = orch._build_messages(sid)
    system_msgs = [m for m in msgs if m["role"] == "system"]
    assert len(system_msgs) == 1
    assert msgs[0]["role"] == "system"
    assert f"image_id={img_id}" in msgs[0]["content"]  # context hoisted into leading system block


# --- LoopState unit tests ---

def test_loop_state_initial_values(tmp_path, kg_path):
    from app.agent.orchestrator import LoopState
    state = LoopState(session_id=42, max_iter=5, timeout_seconds=30)
    assert state.session_id == 42
    assert state.max_iter == 5
    assert state.iteration == 0
    assert state.outcome == "pending"
    assert state.turn_user_msg_id is None
    assert state.messages == []
    assert state.tool_records == []
    assert isinstance(state.cross_turn_cache, set)
    assert state.started_at > 0
    assert state.deadline is not None
    assert state.deadline > state.started_at


def test_loop_state_no_deadline_when_timeout_zero(tmp_path, kg_path):
    from app.agent.orchestrator import LoopState
    state = LoopState(session_id="test_session", max_iter=5, timeout_seconds=0)
    assert state.deadline is None
    assert not state.is_timed_out()


def test_loop_state_has_iterations_left(tmp_path, kg_path):
    from app.agent.orchestrator import LoopState
    state = LoopState(session_id="test_session", max_iter=3, timeout_seconds=0)
    assert state.has_iterations_left()
    state.iteration = 2
    assert state.has_iterations_left()
    state.iteration = 3
    assert not state.has_iterations_left()


def test_loop_state_is_timed_out(tmp_path, kg_path):
    import time
    from app.agent.orchestrator import LoopState
    state = LoopState(session_id="test_session", max_iter=5, timeout_seconds=0.001)
    time.sleep(0.01)
    assert state.is_timed_out()


# --- _session_tool_caches should not exist ---

def test_no_session_tool_caches_module_var():
    import app.agent.orchestrator as m
    assert not hasattr(m, "_session_tool_caches")


# --- tool_traces integration via orchestrator ---

def test_tool_traces_written_on_tool_call(tmp_path, kg_path):
    script = [
        ("", [("search_standards", {"query": "基坑 防护"})]),
        ("基坑周边应设置防护栏杆。", []),
    ]
    orch, db, _ = _orch(tmp_path, kg_path, script)
    sid = db.create_session()
    orch.handle_message(sid, "基坑临边怎么防护?")

    traces = db.get_tool_traces(sid)
    assert len(traces) == 1
    t = traces[0]
    assert t.tool_name == "search_standards"
    assert t.outcome == "ok"
    assert t.loop_outcome == "no_tool_calls"
    assert t.iteration == 0
    assert "基坑" in t.args_json


def test_tool_traces_guard_blocked_recorded(tmp_path, kg_path):
    script = [
        ("", [("search_standards", {"query": "基坑"})]),
        ("", [("search_standards", {"query": "基坑"})]),   # duplicate → guard_blocked
        ("已查到。", []),
    ]
    orch, db, _ = _orch(tmp_path, kg_path, script)
    sid = db.create_session()
    orch.handle_message(sid, "基坑?")

    traces = db.get_tool_traces(sid)
    assert len(traces) == 2
    outcomes = {t.outcome for t in traces}
    assert "ok" in outcomes
    assert "guard_blocked" in outcomes


def test_cross_turn_cache_via_loop_state(tmp_path, kg_path):
    """Cross-turn cache in LoopState blocks repeated cacheable calls across turns."""
    from app.agent.orchestrator import _session_cross_caches
    db = Database(str(tmp_path / "t.db"))
    kg = KGStore.load(str(kg_path))

    def ctx_factory(session_id):
        return ToolContext(db=db, kg=kg, standards=FakeStandards(), intake=FakeIntake(),
                          report_dir=str(tmp_path), session_id=session_id)

    # First turn: model calls search_standards once → ok
    script1 = [
        ("", [("search_standards", {"query": "基坑"})]),
        ("第一轮回答。", []),
    ]
    orch = Orchestrator(db=db, agent_client=ScriptedAgent(script1), agent_model="x",
                        ctx_factory=ctx_factory, max_iterations=5)
    sid = db.create_session()
    orch.handle_message(sid, "第一问")

    # Second turn: model re-calls same query → cross-turn cache should block it
    script2 = [
        ("", [("search_standards", {"query": "基坑"})]),   # cache hit → guard_blocked
        ("第二轮回答。", []),
    ]
    orch._client = ScriptedAgent(script2)
    orch.handle_message(sid, "第二问")

    traces = db.get_tool_traces(sid)
    second_turn_traces = [t for t in traces if t.turn_user_msg_id == db.get_messages(sid)[-2].id
                          or True]
    # The second call to search_standards with same args should be guard_blocked
    blocked = [t for t in traces if t.outcome == "guard_blocked"]
    assert len(blocked) == 1
    assert blocked[0].tool_name == "search_standards"


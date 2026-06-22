from app.agent.prompts import SYSTEM_PROMPT, render_detection_message
from app.vlm.detector import DetectionResult, Hazard


def test_system_prompt_mentions_confirmation_and_tools():
    assert "是否正确" in SYSTEM_PROMPT
    assert "submit_correction" in SYSTEM_PROMPT
    assert "search_standards" in SYSTEM_PROMPT


def test_render_detection_message_lists_hazards():
    r = DetectionResult(scene="four_openings_edges", hazards=[
        Hazard(object_id="foundation_pit_edge_protection", object_name="基坑临边防护",
               status="confirmed_hazard", hazard_type_id="missing_protection", hazard_type="防护缺失",
               bbox=[0, 278, 999, 999], visual_evidence="未见连续防护栏杆", rule_basis="rb",
               evidence_sufficiency="sufficient", uncertainty_reason=None, reasoning_chain=[])])
    msg = render_detection_message(r)
    assert "基坑临边防护" in msg and "防护缺失" in msg
    assert "是否正确" in msg

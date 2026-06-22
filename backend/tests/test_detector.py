import json

import pytest

from app.vlm.detector import Detector, DetectionError


class FakeChatCompletions:
    def __init__(self, content: str):
        self._content = content

    def create(self, **kwargs):
        class _Msg:
            content = self._content
        class _Choice:
            message = _Msg()
        class _Resp:
            choices = [_Choice()]
        return _Resp()


class FakeClient:
    def __init__(self, content: str):
        self.chat = type("C", (), {"completions": FakeChatCompletions(content)})()


def _detector_with(content: str, kg_path) -> Detector:
    from app.kg.store import KGStore
    return Detector(client=FakeClient(content), model="vlm-x", kg=KGStore.load(str(kg_path)))


def test_parse_wrapped_hazards(sample_vlm_response, tiny_png, kg_path):
    det = _detector_with(json.dumps(sample_vlm_response, ensure_ascii=False), kg_path)
    result = det.detect(str(tiny_png))
    assert result.scene == "four_openings_edges" or result.scene == "四口五临边"
    assert len(result.hazards) == 1
    h = result.hazards[0]
    assert h.object_id == "foundation_pit_edge_protection"
    assert h.bbox == [0, 278, 999, 999]
    assert h.hazard_type_id == "missing_protection"
    assert h.status == "confirmed_hazard"


def test_parse_bare_list(sample_vlm_hazard, tiny_png, kg_path):
    det = _detector_with(json.dumps([sample_vlm_hazard], ensure_ascii=False), kg_path)
    result = det.detect(str(tiny_png))
    assert len(result.hazards) == 1


def test_fenced_json_is_parsed(sample_vlm_response, tiny_png, kg_path):
    content = "```json\n" + json.dumps(sample_vlm_response, ensure_ascii=False) + "\n```"
    det = _detector_with(content, kg_path)
    assert len(det.detect(str(tiny_png)).hazards) == 1


def test_invalid_json_raises(tiny_png, kg_path):
    det = _detector_with("not json at all", kg_path)
    with pytest.raises(DetectionError):
        det.detect(str(tiny_png))

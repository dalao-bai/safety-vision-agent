"""Tests for the v0.2 agent tool registry (make_tools factory).

Tools are exercised by calling them directly through the LangChain @tool
interface (.invoke()). analyze_image uses a fake VLM client; the other tools
run as deterministic transforms over a pre-seeded DB analysis result.
"""

from __future__ import annotations

import json

import pytest

from app.agent.tools import TOOL_NAMES, make_tools
from app.db import repositories as repo
from app.db.sqlite import connect, init_db
from app.models.schemas import AnalysisResult
from app.services.responses_client import ResponsesResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def conn(tmp_path):
    c = connect(str(tmp_path / "tools.db"))
    init_db(c)
    yield c
    c.close()


@pytest.fixture
def cid(conn):
    return repo.create_conversation(conn)


def _analysis_payload():
    return {
        "summary": "多处隐患",
        "hazards": [
            {
                "name": "未系安全带",
                "location": "脚手架顶部",
                "risk_level": "high",
                "basis": "工人高处作业无防护",
                "remediation": "佩戴安全带并设置防护栏",
                "confidence": 0.8,
            },
            {
                "name": "临边无防护",
                "location": "楼层边缘",
                "risk_level": "critical",
                "basis": "楼层临边缺少护栏",
                "remediation": "安装临边防护栏杆",
                "confidence": 0.95,
            },
            {
                "name": "材料堆放杂乱",
                "location": "通道处",
                "risk_level": "low",
                "basis": "通道被材料占用",
                "remediation": "清理通道，规范堆放",
                "confidence": 0.6,
            },
        ],
        "needs_followup": False,
        "followup_question": None,
    }


class _FakeVLMClient:
    def __init__(self, text):
        self._text = text

    def create(self, model, input_items, tools=None, text_format=None):
        return ResponsesResult(text=self._text, provider_id="resp_v", raw=None)


def _tools(conn, cid, vlm_text=None, regulation_search=None, report_scheduler=None):
    vlm = _FakeVLMClient(vlm_text or "") if vlm_text is not None else _FakeVLMClient("")
    tool_list = make_tools(
        conn=conn,
        conversation_id=cid,
        user_id=None,
        vlm_client=vlm,
        vlm_model="vlm",
        regulation_search=regulation_search,
        report_scheduler=report_scheduler,
    )
    return {t.name: t for t in tool_list}


# ---------------------------------------------------------------------------
# Registry smoke test
# ---------------------------------------------------------------------------

def test_tool_names_match_v02_set():
    assert TOOL_NAMES == {
        "analyze_image",
        "explain_basis",
        "rank_risks",
        "suggest_remediation",
        "search_regulations",
        "generate_report",
        "query_history",
    }


def test_make_tools_returns_all_seven(conn, cid):
    tools = _tools(conn, cid)
    assert set(tools.keys()) == TOOL_NAMES


# ---------------------------------------------------------------------------
# analyze_image
# ---------------------------------------------------------------------------

def test_analyze_image_calls_vlm_and_returns_summary(conn, cid, tmp_path):
    img = tmp_path / "x.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0bytes")
    repo.add_uploaded_image(conn, cid, str(img), "x.jpg", "image/jpeg", 100)

    valid = json.dumps(_analysis_payload(), ensure_ascii=False)
    tools = _tools(conn, cid, vlm_text=valid)

    result = tools["analyze_image"].invoke({"question": ""})

    assert result["available"] is True
    assert result["hazard_count"] == 3
    # Analysis was persisted to DB.
    saved = repo.get_latest_analysis(conn, cid)
    assert saved is not None
    assert len(saved["hazards"]) == 3


def test_analyze_image_without_image_reports_unavailable(conn, cid):
    tools = _tools(conn, cid)
    result = tools["analyze_image"].invoke({"question": ""})
    assert result["available"] is False


# ---------------------------------------------------------------------------
# explain_basis
# ---------------------------------------------------------------------------

def test_explain_basis_returns_all_bases(conn, cid):
    repo.save_analysis_result(conn, cid, _analysis_payload())
    tools = _tools(conn, cid)

    result = tools["explain_basis"].invoke({"hazard_name": ""})

    assert result["available"] is True
    assert len(result["bases"]) == 3
    assert result["bases"][0]["name"] == "未系安全带"
    assert "basis" in result["bases"][0]
    assert "location" in result["bases"][0]


def test_explain_basis_for_named_hazard(conn, cid):
    repo.save_analysis_result(conn, cid, _analysis_payload())
    tools = _tools(conn, cid)

    result = tools["explain_basis"].invoke({"hazard_name": "临边无防护"})

    assert result["available"] is True
    assert len(result["bases"]) == 1
    assert result["bases"][0]["name"] == "临边无防护"


def test_explain_basis_without_analysis_reports_unavailable(conn, cid):
    tools = _tools(conn, cid)
    result = tools["explain_basis"].invoke({"hazard_name": ""})
    assert result["available"] is False
    assert "还没有" in result["message"]


# ---------------------------------------------------------------------------
# rank_risks
# ---------------------------------------------------------------------------

def test_rank_risks_orders_by_severity_then_confidence(conn, cid):
    repo.save_analysis_result(conn, cid, _analysis_payload())
    tools = _tools(conn, cid)

    result = tools["rank_risks"].invoke({})

    ranked = result["ranked"]
    # critical > high > low
    assert [r["name"] for r in ranked] == ["临边无防护", "未系安全带", "材料堆放杂乱"]
    assert ranked[0]["rank"] == 1


def test_rank_risks_without_analysis_reports_unavailable(conn, cid):
    tools = _tools(conn, cid)
    result = tools["rank_risks"].invoke({})
    assert result["available"] is False
    assert "还没有" in result["message"]


# ---------------------------------------------------------------------------
# suggest_remediation
# ---------------------------------------------------------------------------

def test_suggest_remediation_returns_all(conn, cid):
    repo.save_analysis_result(conn, cid, _analysis_payload())
    tools = _tools(conn, cid)

    result = tools["suggest_remediation"].invoke({"hazard_name": ""})

    assert result["available"] is True
    assert len(result["remediations"]) == 3
    assert all("remediation" in r for r in result["remediations"])


def test_suggest_remediation_for_named_hazard(conn, cid):
    repo.save_analysis_result(conn, cid, _analysis_payload())
    tools = _tools(conn, cid)

    result = tools["suggest_remediation"].invoke({"hazard_name": "材料堆放杂乱"})

    assert result["available"] is True
    assert len(result["remediations"]) == 1
    assert result["remediations"][0]["name"] == "材料堆放杂乱"


def test_suggest_remediation_without_analysis_reports_unavailable(conn, cid):
    tools = _tools(conn, cid)
    result = tools["suggest_remediation"].invoke({"hazard_name": ""})
    assert result["available"] is False
    assert "还没有" in result["message"]


# ---------------------------------------------------------------------------
# search_regulations
# ---------------------------------------------------------------------------

def test_search_regulations_returns_hits(conn, cid):
    def _fake_search(query, top_k=3):
        return [{"text": "安全带应定期检查", "original_name": "建设规范.pdf"}]

    tools = _tools(conn, cid, regulation_search=_fake_search)
    result = tools["search_regulations"].invoke({"query": "安全带"})

    assert result["available"] is True
    assert len(result["results"]) == 1
    assert result["results"][0]["text"] == "安全带应定期检查"


def test_search_regulations_without_callback_reports_unavailable(conn, cid):
    tools = _tools(conn, cid)
    result = tools["search_regulations"].invoke({"query": "安全带"})
    assert result["available"] is False


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------

def test_generate_report_returns_task_id(conn, cid):
    def _fake_scheduler(start, end):
        return "task-abc"

    tools = _tools(conn, cid, report_scheduler=_fake_scheduler)
    result = tools["generate_report"].invoke({"start_date": "2024-01-01", "end_date": "2024-12-31"})

    assert result["available"] is True
    assert result["task_id"] == "task-abc"


def test_generate_report_without_dates_returns_unavailable(conn, cid):
    """Without dates the tool must ask the agent to confirm the range first."""
    def _fake_scheduler(start, end):
        return "task-abc"

    tools = _tools(conn, cid, report_scheduler=_fake_scheduler)
    result = tools["generate_report"].invoke({"start_date": "", "end_date": ""})

    assert result["available"] is False
    assert "时间范围" in result["message"]


def test_generate_report_without_callback_reports_unavailable(conn, cid):
    tools = _tools(conn, cid)
    result = tools["generate_report"].invoke({"start_date": "2024-01-01", "end_date": "2024-12-31"})
    assert result["available"] is False


# ---------------------------------------------------------------------------
# query_history
# ---------------------------------------------------------------------------

def test_query_history_returns_stats(conn, cid):
    uid = repo.create_user(conn, "tester", "h")
    repo.upsert_hazard_stat(conn, uid, "高处坠落", "high", cid)

    vlm = _FakeVLMClient("")
    tool_list = make_tools(
        conn=conn,
        conversation_id=cid,
        user_id=uid,
        vlm_client=vlm,
        vlm_model="vlm",
    )
    tools = {t.name: t for t in tool_list}

    result = tools["query_history"].invoke({"start_date": "", "end_date": ""})

    assert result["available"] is True
    assert len(result["hazard_stats"]) == 1
    assert result["hazard_stats"][0]["hazard_type"] == "高处坠落"


def test_query_history_without_user_id_reports_unavailable(conn, cid):
    tools = _tools(conn, cid)
    result = tools["query_history"].invoke({"start_date": "", "end_date": ""})
    assert result["available"] is False

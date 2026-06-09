"""Agent tool registry — LangGraph-compatible @tool factory (v0.2).

Replaces the v0.1 ToolContext dataclass + execute_tool() dispatcher with a
make_tools() factory that binds per-request context via closure and returns a
list of LangChain @tool-decorated functions ready for create_react_agent.

Analysis state is no longer shared in-memory across tools. Each tool that
needs the latest analysis fetches it from the DB via
repo.get_latest_analysis(), which is the authoritative source after
analyze_image() persists its result.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Callable

from langchain_core.tools import tool

from app.db import repositories as repo
from app.models.schemas import AnalysisResult
from app.services.vlm_analyzer import analyze_image as run_vlm_analysis

# Ordering for risk severity, highest first.
_RISK_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

_NO_ANALYSIS_STR = json.dumps(
    {"available": False, "message": "当前对话还没有可用的隐患分析结果，请先上传照片进行分析。"},
    ensure_ascii=False,
)

# Canonical set of tool names for reference (e.g. orchestrator allow-listing).
TOOL_NAMES: frozenset[str] = frozenset({
    "analyze_image",
    "explain_basis",
    "rank_risks",
    "suggest_remediation",
    "search_regulations",
    "generate_report",
    "query_history",
})


def make_tools(
    conn: sqlite3.Connection,
    conversation_id: str,
    user_id: str | None,
    vlm_client,           # ResponsesClient — used by analyze_image
    vlm_model: str,       # model name passed to the VLM
    regulation_search: Callable[..., list[dict]] | None = None,
    report_scheduler: Callable[..., str] | None = None,
) -> list:
    """Return a list of LangChain @tool functions bound to this request's context.

    All seven tools capture conn, conversation_id, user_id, and the optional
    service callbacks via closure so the agent can call them with only their
    domain arguments.
    """

    @tool
    def analyze_image(question: str = "") -> str:
        """分析当前上传的施工现场照片，识别安全隐患并返回结构化结果。首次分析或用户上传新照片时调用。"""
        try:
            image_row = repo.get_latest_image(conn, conversation_id)
            if image_row is None:
                return json.dumps({"available": False, "message": "没有可分析的照片，请先上传施工现场照片。"}, ensure_ascii=False)

            # Secondary ownership check: verify the conversation belongs to this user.
            if user_id is not None:
                conv = repo.get_conversation(conn, conversation_id)
                if conv is None or conv["user_id"] != user_id:
                    return json.dumps({"available": False, "message": "无权访问该对话的图片。"}, ensure_ascii=False)

            outcome = run_vlm_analysis(
                vlm_client,
                vlm_model,
                image_row["stored_path"],
                image_row["mime_type"],
                question or None,
            )

            # Persist raw VLM response for audit regardless of success/failure.
            repo.save_model_response(
                conn,
                conversation_id,
                model_role="vlm",
                status="success" if outcome.ok else "error",
                provider_id=outcome.provider_id,
                raw_text=outcome.raw_text,
                error=outcome.error,
            )

            if not outcome.ok:
                return json.dumps({"available": False, "message": f"图像分析失败：{outcome.error}"}, ensure_ascii=False)

            result = outcome.result
            repo.save_analysis_result(
                conn,
                conversation_id,
                result.model_dump(mode="json"),
                image_id=image_row["id"],
            )

            return json.dumps({
                "available": True,
                "summary": result.summary,
                "hazard_count": len(result.hazards),
                "hazards": [h.model_dump(mode="json") for h in result.hazards],
                "needs_followup": result.needs_followup,
                "followup_question": result.followup_question,
            }, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"available": False, "message": f"analyze_image 执行错误：{exc}"}, ensure_ascii=False)

    @tool
    def explain_basis(hazard_name: str = "") -> str:
        """解释已识别隐患的判断依据。当用户询问依据、理由或为什么不安全时调用。"""
        try:
            raw = repo.get_latest_analysis(conn, conversation_id)
            if raw is None:
                return _NO_ANALYSIS_STR
            analysis = AnalysisResult.model_validate(raw)
            hazards = analysis.hazards
            if hazard_name:
                hazards = [h for h in hazards if h.name == hazard_name]
                if not hazards:
                    return json.dumps({"available": False, "message": f"未找到名为 {hazard_name!r} 的隐患。"}, ensure_ascii=False)
            return json.dumps({
                "available": True,
                "bases": [
                    {"name": h.name, "location": h.location, "basis": h.basis}
                    for h in hazards
                ],
            }, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"available": False, "message": f"explain_basis 执行错误：{exc}"}, ensure_ascii=False)

    @tool
    def rank_risks() -> str:
        """按严重程度对已识别的隐患排序。当用户询问哪个最严重或优先级时调用。"""
        try:
            raw = repo.get_latest_analysis(conn, conversation_id)
            if raw is None:
                return _NO_ANALYSIS_STR
            analysis = AnalysisResult.model_validate(raw)
            ranked = sorted(
                analysis.hazards,
                key=lambda h: (_RISK_ORDER.get(h.risk_level.value, 99), -h.confidence),
            )
            return json.dumps({
                "available": True,
                "ranked": [
                    {
                        "rank": i + 1,
                        "name": h.name,
                        "risk_level": h.risk_level.value,
                        "confidence": h.confidence,
                    }
                    for i, h in enumerate(ranked)
                ],
            }, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"available": False, "message": f"rank_risks 执行错误：{exc}"}, ensure_ascii=False)

    @tool
    def suggest_remediation(hazard_name: str = "") -> str:
        """针对已识别隐患给出整改建议。当用户询问如何整改、修复或处理时调用。"""
        try:
            raw = repo.get_latest_analysis(conn, conversation_id)
            if raw is None:
                return _NO_ANALYSIS_STR
            analysis = AnalysisResult.model_validate(raw)
            hazards = analysis.hazards
            if hazard_name:
                hazards = [h for h in hazards if h.name == hazard_name]
                if not hazards:
                    return json.dumps({"available": False, "message": f"未找到名为 {hazard_name!r} 的隐患。"}, ensure_ascii=False)
            return json.dumps({
                "available": True,
                "remediations": [
                    {"name": h.name, "remediation": h.remediation}
                    for h in hazards
                ],
            }, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"available": False, "message": f"suggest_remediation 执行错误：{exc}"}, ensure_ascii=False)

    @tool
    def search_regulations(query: str) -> str:
        """在规范库中语义检索相关的安全规范条文。当用户询问某做法依据哪条规范、相关标准要求时调用。"""
        try:
            if regulation_search is None:
                return json.dumps({"available": False, "message": "规范检索能力当前不可用。"}, ensure_ascii=False)
            if not query:
                return json.dumps({"available": False, "message": "请提供检索关键词。"}, ensure_ascii=False)
            hits = regulation_search(query, top_k=3)
            return json.dumps({
                "available": True,
                "query": query,
                "results": [
                    {"text": h.get("text"), "source": h.get("original_name")}
                    for h in hits
                ],
            }, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"available": False, "message": f"search_regulations 执行错误：{exc}"}, ensure_ascii=False)

    @tool
    def generate_report(start_date: str = "", end_date: str = "") -> str:
        """生成跨对话的合规报告(.docx)。当用户说\"生成报告\"时调用；必须先向用户确认时间范围(start_date/end_date)。"""
        try:
            if report_scheduler is None:
                return json.dumps({"available": False, "message": "报告生成能力当前不可用。"}, ensure_ascii=False)
            if not start_date and not end_date:
                return json.dumps({
                    "available": False,
                    "message": "请先与用户确认报告的时间范围（start_date / end_date），再调用本工具。",
                }, ensure_ascii=False)
            task_id = report_scheduler(start_date or None, end_date or None)
            return json.dumps({
                "available": True,
                "task_id": task_id,
                "message": "报告生成任务已提交，可凭 task_id 查询状态与下载。",
            }, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"available": False, "message": f"generate_report 执行错误：{exc}"}, ensure_ascii=False)

    @tool
    def query_history(start_date: str = "", end_date: str = "") -> str:
        """查询当前用户在某时间段内的历史隐患统计。当用户询问过去的隐患记录、历史趋势时调用。"""
        try:
            if conn is None or user_id is None:
                return json.dumps({"available": False, "message": "历史查询能力当前不可用。"}, ensure_ascii=False)
            stats = repo.get_hazard_stats_by_user(
                conn,
                user_id,
                start=start_date or None,
                end=end_date or None,
            )
            return json.dumps({
                "available": True,
                "hazard_stats": [
                    {
                        "hazard_type": s["hazard_type"],
                        "risk_level": s["risk_level"],
                        "occurrence_count": s["occurrence_count"],
                        "last_seen_at": s["last_seen_at"],
                    }
                    for s in stats
                ],
            }, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"available": False, "message": f"query_history 执行错误：{exc}"}, ensure_ascii=False)

    return [
        analyze_image,
        explain_basis,
        rank_risks,
        suggest_remediation,
        search_regulations,
        generate_report,
        query_history,
    ]

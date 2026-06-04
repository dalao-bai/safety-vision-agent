from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Any

import httpx

from app.db import repositories
from app.models.schemas import FusedResult, ReportRequest
from app.services.evidence_fusion import EvidenceFusionService
from app.services.file_storage import get_uploaded_image_path
from app.services.memory import hazard_by_index, latest_result_context
from app.services.remediation_service import RemediationService
from app.services.report_generator import ReportGenerator
from app.services.rule_retriever import RuleRetriever
from app.services.vlm_client import VLMClient
from app.services.yolo_detector import YOLOHelmetDetector


def _call_payload(record) -> dict:
    return {
        "tool": record.tool_name,
        "status": record.status,
        "input": record.input_json,
        "output": record.output_json,
        "latency_ms": record.latency_ms,
    }


async def _record_async_tool(
    conversation_id: str,
    analysis_id: str | None,
    tool_name: str,
    input_json: dict,
    fn: Callable[[], Awaitable[Any]],
) -> tuple[Any | None, dict]:
    started = perf_counter()
    try:
        result = await fn()
        output = result.model_dump() if hasattr(result, "model_dump") else result
        output_json = output if isinstance(output, dict) else {"items": output} if isinstance(output, list) else {"result": str(output)}
        record = repositories.create_tool_call(
            conversation_id,
            analysis_id,
            tool_name,
            "ok",
            input_json,
            output_json,
            (perf_counter() - started) * 1000,
        )
        return result, _call_payload(record)
    except (httpx.HTTPError, TimeoutError, OSError) as exc:
        record = repositories.create_tool_call(
            conversation_id,
            analysis_id,
            tool_name,
            "error",
            input_json,
            {"error": str(exc), "type": exc.__class__.__name__},
            (perf_counter() - started) * 1000,
        )
        return None, _call_payload(record)


def _record_sync_tool(
    conversation_id: str,
    analysis_id: str | None,
    tool_name: str,
    input_json: dict,
    fn: Callable[[], Any],
) -> tuple[Any | None, dict]:
    started = perf_counter()
    try:
        result = fn()
        output = result.model_dump() if hasattr(result, "model_dump") else result
        output_json = output if isinstance(output, dict) else {"items": output} if isinstance(output, list) else {"result": str(output)}
        record = repositories.create_tool_call(
            conversation_id,
            analysis_id,
            tool_name,
            "ok",
            input_json,
            output_json,
            (perf_counter() - started) * 1000,
        )
        return result, _call_payload(record)
    except (httpx.HTTPError, TimeoutError, OSError, FileNotFoundError) as exc:
        record = repositories.create_tool_call(
            conversation_id,
            analysis_id,
            tool_name,
            "error",
            input_json,
            {"error": str(exc), "type": exc.__class__.__name__},
            (perf_counter() - started) * 1000,
        )
        return None, _call_payload(record)


def retrieve_rules_tool(conversation_id: str, analysis_id: str | None, object_id: str | None = None) -> tuple[list[dict], dict]:
    result, call = _record_sync_tool(
        conversation_id,
        analysis_id,
        "rule_retrieval_tool",
        {"object_id": object_id},
        lambda: RuleRetriever().retrieve_for_prompt(object_id=object_id),
    )
    return result or [], call


async def run_image_analysis_tool(
    conversation_id: str,
    message: str,
    file_id: str | None,
    image_path: str | None,
    selected_bbox: list[float] | None,
) -> dict:
    resolved_image_path = get_uploaded_image_path(file_id, image_path)
    analysis = repositories.create_analysis_task(conversation_id, resolved_image_path, message, status="running")
    tool_calls: list[dict] = []

    rules, call = retrieve_rules_tool(conversation_id, analysis.id)
    tool_calls.append(call)

    vlm_result, call = await _record_async_tool(
        conversation_id,
        analysis.id,
        "vlm_hazard_analysis_tool",
        {"image_path": resolved_image_path, "question": message, "target_bbox": selected_bbox},
        lambda: VLMClient().analyze_image(resolved_image_path, message, rules, selected_bbox),
    )
    tool_calls.append(call)

    yolo_result, call = _record_sync_tool(
        conversation_id,
        analysis.id,
        "yolo_helmet_detection_tool",
        {"image_path": resolved_image_path},
        lambda: YOLOHelmetDetector().detect(resolved_image_path),
    )
    tool_calls.append(call)

    if vlm_result is None or yolo_result is None:
        repositories.update_analysis_status(analysis.id, "failed")
        return {
            "analysis_id": analysis.id,
            "image_path": resolved_image_path,
            "fused_result": None,
            "tool_calls": tool_calls,
            "error": "visual_tool_failed",
        }

    fused = EvidenceFusionService().fuse(vlm_result, yolo_result)
    repositories.save_analysis_results(analysis.id, vlm_result.model_dump(), yolo_result.model_dump(), fused.model_dump())
    return {
        "analysis_id": analysis.id,
        "image_path": resolved_image_path,
        "fused_result": fused,
        "tool_calls": tool_calls,
    }


def answer_rule_basis_tool(conversation_id: str, message: str) -> dict:
    hazard_context = hazard_by_index(conversation_id, message)
    if not hazard_context or hazard_context.get("error"):
        return hazard_context
    hazard = hazard_context["hazard"]
    rules, call = retrieve_rules_tool(conversation_id, hazard_context["analysis"]["id"], hazard.get("object_id"))
    return {**hazard_context, "rules": rules, "tool_calls": [call]}


def create_remediation_tool(conversation_id: str, message: str) -> dict:
    hazard_context = hazard_by_index(conversation_id, message)
    if not hazard_context or hazard_context.get("error"):
        return hazard_context
    hazard = hazard_context["hazard"]
    service = RemediationService()
    task = repositories.create_remediation_task(
        conversation_id,
        hazard_context["analysis"]["id"],
        hazard_context["index"],
        service.default_title(hazard, hazard_context["index"]),
        service.default_recommendation(hazard),
        None,
        None,
        hazard,
    )
    return {**hazard_context, "remediation_task": dict(task)}


def generate_report_tool(conversation_id: str) -> dict:
    context = latest_result_context(conversation_id)
    if not context:
        return {}
    result = FusedResult.model_validate(context["fused_result"])
    report = ReportGenerator().generate(ReportRequest(conversation_id=conversation_id, fused_result=result))
    record = repositories.create_report(conversation_id, context["analysis"]["id"], report.title, report.markdown)
    return {"report": report.model_dump(), "report_record": dict(record), "analysis": context["analysis"], "fused_result": result.model_dump()}

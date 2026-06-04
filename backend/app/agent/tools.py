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


def _summarize_output(output_json: dict) -> dict:
    summary: dict[str, Any] = {}
    if "summary" in output_json:
        summary["summary"] = output_json["summary"]
    if "hazards" in output_json:
        summary["hazard_count"] = len(output_json.get("hazards") or [])
    if "uncertain_items" in output_json:
        summary["uncertain_count"] = len(output_json.get("uncertain_items") or [])
    if "detections" in output_json:
        summary["detection_count"] = len(output_json.get("detections") or [])
    if "error" in output_json:
        summary["error"] = output_json["error"]
    return summary or output_json


def _call_payload(record) -> dict:
    return {
        "tool": record.tool_name,
        "status": record.status,
        "input": record.input_json,
        "output": _summarize_output(record.output_json),
        "observation": _summarize_output(record.output_json),
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


def _with_source(value: Any, source: dict) -> dict:
    item = value.model_dump() if hasattr(value, "model_dump") else dict(value)
    return {
        **item,
        "source_file_id": source.get("file_id"),
        "source_analysis_id": source.get("analysis_id"),
        "source_label": source.get("source_label"),
    }


def _source_fused_result(fused: FusedResult, source: dict) -> FusedResult:
    fused_json = fused.model_dump()
    fused_json["hazards"] = [_with_source(item, source) for item in fused_json.get("hazards", [])]
    fused_json["detections"] = [_with_source(item, source) for item in fused_json.get("detections", [])]
    fused_json["uncertain_items"] = [_with_source(item, source) for item in fused_json.get("uncertain_items", [])]
    return FusedResult.model_validate(fused_json)


async def run_multi_image_analysis_tool(
    conversation_id: str,
    message: str,
    file_ids: list[str],
    image_paths: list[str],
    selected_bbox: list[float] | None,
) -> dict:
    image_refs = [{"file_id": file_id, "image_path": None} for file_id in file_ids]
    image_refs.extend({"file_id": None, "image_path": image_path} for image_path in image_paths)
    if not image_refs:
        return {"error": "image_required", "tool_calls": []}

    analyses: list[dict] = []
    errors: list[dict] = []
    tool_calls: list[dict] = []
    combined = {
        "hazards": [],
        "detections": [],
        "uncertain_items": [],
        "uncertain_followups": [],
        "summary": "",
        "recommendations": [],
    }

    for index, ref in enumerate(image_refs, start=1):
        source_label = f"图片 {index}"
        result = await run_image_analysis_tool(
            conversation_id=conversation_id,
            message=message,
            file_id=ref["file_id"],
            image_path=ref["image_path"],
            selected_bbox=selected_bbox,
        )
        analysis_id = result.get("analysis_id")
        source = {"file_id": ref["file_id"], "analysis_id": analysis_id, "source_label": source_label}
        tool_calls.extend(result.get("tool_calls", []))
        analysis_record = {
            "source_label": source_label,
            "file_id": ref["file_id"],
            "image_path": result.get("image_path") or ref["image_path"],
            "analysis_id": analysis_id,
            "error": result.get("error"),
        }
        analyses.append(analysis_record)
        if result.get("error"):
            errors.append({"code": result["error"], "source_label": source_label, "analysis_id": analysis_id})
            continue
        fused = result.get("fused_result")
        if not fused:
            continue
        if len(image_refs) == 1:
            sourced = _source_fused_result(fused, source)
            repositories.save_fused_result(analysis_id, sourced.model_dump())
            return {
                "analysis_id": analysis_id,
                "analyses": analyses,
                "fused_result": sourced,
                "tool_calls": tool_calls,
            }
        fused_json = fused.model_dump() if hasattr(fused, "model_dump") else fused
        combined["hazards"].extend(_with_source(item, source) for item in fused_json.get("hazards", []))
        combined["detections"].extend(_with_source(item, source) for item in fused_json.get("detections", []))
        combined["uncertain_items"].extend(_with_source(item, source) for item in fused_json.get("uncertain_items", []))
        combined["uncertain_followups"].extend(fused_json.get("uncertain_followups", []))
        combined["recommendations"].extend(fused_json.get("recommendations", []))

    hazard_count = len(combined["hazards"])
    uncertain_count = len(combined["uncertain_items"])
    if not any(not item.get("error") for item in analyses):
        return {
            "analysis_id": analyses[-1]["analysis_id"] if analyses else None,
            "analyses": analyses,
            "fused_result": None,
            "tool_calls": tool_calls,
            "error": "visual_tool_failed",
            "errors": errors,
        }
    combined["summary"] = f"共分析 {len(image_refs)} 张图片，发现 {hazard_count} 个明确隐患，{uncertain_count} 个证据不足项。"
    combined["recommendations"] = list(dict.fromkeys(combined["recommendations"]))
    aggregate = repositories.create_analysis_task(conversation_id, "aggregate:multi-image", message, status="running")
    repositories.save_fused_result(aggregate.id, combined)
    return {
        "analysis_id": aggregate.id,
        "analyses": analyses,
        "fused_result": FusedResult.model_validate(combined),
        "tool_calls": tool_calls,
        "errors": errors,
    }


def memory_lookup_tool(conversation_id: str) -> dict:
    context = latest_result_context(conversation_id)
    if not context:
        return {}
    return {
        "analysis": context["analysis"],
        "fused_result": context["result"].model_dump(),
        "tool_calls": [],
    }


def score_risk_tool(fused_result: dict) -> dict:
    hazards = []
    for hazard in fused_result.get("hazards") or []:
        confidence = hazard.get("confidence")
        score = 50
        reasons = ["基础隐患风险"]
        hazard_type = str(hazard.get("hazard_type") or hazard.get("hazard_type_id") or "")
        visual = str(hazard.get("visual_evidence") or "")
        rule = str(hazard.get("rule") or "")
        if any(keyword in hazard_type + visual + rule for keyword in ["临边", "洞口", "坠落", "防护"]):
            score += 20
            reasons.append("涉及临边/洞口/坠落防护")
        if any(keyword in visual for keyword in ["人员", "工人", "靠近", "作业"]):
            score += 15
            reasons.append("可见人员接近风险区域")
        if confidence is not None:
            if confidence >= 0.8:
                score += 10
                reasons.append("证据置信度较高")
            elif confidence < 0.5:
                score -= 15
                reasons.append("证据置信度偏低")
        if hazard.get("evidence_sufficiency") == "insufficient":
            score -= 20
            reasons.append("证据不足，降低确认优先级")
        score = max(0, min(100, score))
        if score >= 85:
            level = "critical"
        elif score >= 65:
            level = "high"
        elif score >= 40:
            level = "medium"
        else:
            level = "low"
        hazards.append({**hazard, "risk_score": score, "risk_level": level, "risk_reasons": reasons})

    hazards.sort(key=lambda item: (item.get("risk_score") or 0, item.get("confidence") or 0), reverse=True)
    scored = {**fused_result, "hazards": hazards}
    return {"fused_result": scored, "tool_calls": []}


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


def generate_report_tool(conversation_id: str, fused_result: dict | None = None) -> dict:
    context = latest_result_context(conversation_id)
    if not context:
        return {}
    result = FusedResult.model_validate(fused_result or context["fused_result"])
    report = ReportGenerator().generate(ReportRequest(conversation_id=conversation_id, fused_result=result))
    record = repositories.create_report(conversation_id, context["analysis"]["id"], report.title, report.markdown)
    return {"report": report.model_dump(), "report_record": dict(record), "analysis": context["analysis"], "fused_result": result.model_dump()}

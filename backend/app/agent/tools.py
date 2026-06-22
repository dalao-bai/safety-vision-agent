from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.kg.store import KGStore
from app.persistence.db import Database
from app.reports.builder import build_markdown_report


@dataclass
class ToolContext:
    db: Database
    kg: KGStore
    standards: Any
    intake: Any
    report_dir: str
    session_id: int


TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "query_kg",
        "description": "查询知识图谱中防护对象或隐患类型的定义、检查范围、合格条件(整改依据)、规则块与标准出处。",
        "parameters": {"type": "object", "properties": {
            "object_id": {"type": "string", "description": "防护对象 id,如 foundation_pit_edge_protection"},
            "hazard_type_id": {"type": "string", "description": "隐患类型 id,如 missing_protection"},
        }}}},
    {"type": "function", "function": {
        "name": "search_standards",
        "description": "在 JGJ 标准原文(向量库)中语义检索相关条文片段,返回原文与出处。",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
            "top_k": {"type": "integer", "default": 3},
        }, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "get_session_hazards",
        "description": "召回本会话已识别的隐患(多轮记忆)。可选按 image_id 过滤。",
        "parameters": {"type": "object", "properties": {
            "image_id": {"type": "integer"}}}}},
    {"type": "function", "function": {
        "name": "submit_correction",
        "description": "当用户指出识别结果不正确并说明原因后,记录纠错并把样本沉入标注流水线待处理队列。",
        "parameters": {"type": "object", "properties": {
            "image_id": {"type": "integer"},
            "note": {"type": "string", "description": "用户说明的错误之处"},
        }, "required": ["image_id", "note"]}}},
    {"type": "function", "function": {
        "name": "export_report",
        "description": "把本会话已确认隐患导出为 Markdown 报告,返回下载路径。",
        "parameters": {"type": "object", "properties": {}}}},
]


def _hazard_brief(h) -> dict:
    return {"image_id": h.image_id, "object_id": h.object_id, "status": h.status,
            "hazard_type_id": h.hazard_type_id, "bbox": h.bbox,
            "visual_evidence": h.visual_evidence, "confirmed": h.confirmed}


def dispatch_tool(name: str, args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    if name == "query_kg":
        oid = args.get("object_id")
        hid = args.get("hazard_type_id")
        out: dict[str, Any] = {}
        if oid:
            obj = ctx.kg.get_object(oid) or {}
            out = {"object_id": oid, "name": obj.get("name", ""),
                   "definition": obj.get("definition", ""),
                   "inspection_scope": obj.get("inspection_scope", []),
                   "qualified_conditions": obj.get("qualified_conditions", []),
                   "remediation": ctx.kg.remediation_for(oid),
                   "rule_blocks": ctx.kg.rule_blocks_for(oid, hid)}
        if hid:
            out["hazard_type"] = ctx.kg.get_hazard_type(hid) or {}
        return out
    if name == "search_standards":
        hits = ctx.standards.search(args["query"], top_k=int(args.get("top_k", 3)))
        return {"hits": hits}
    if name == "get_session_hazards":
        img_id = args.get("image_id")
        if img_id:
            hz = ctx.db.get_hazards(int(img_id))
        else:
            hz = ctx.db.get_session_hazards(ctx.session_id)
        return {"hazards": [_hazard_brief(h) for h in hz]}
    if name == "submit_correction":
        img_id = int(args["image_id"])
        note = args["note"]
        image = ctx.db.get_image(img_id)
        from app.vlm.detector import DetectionResult, Hazard as VHazard
        stored = ctx.db.get_hazards(img_id)
        result = DetectionResult(scene=image.scene, hazards=[
            VHazard(object_id=h.object_id, object_name=(ctx.kg.get_object(h.object_id) or {}).get("name", ""),
                    status=h.status, hazard_type_id=h.hazard_type_id,
                    hazard_type=(ctx.kg.get_hazard_type(h.hazard_type_id) or {}).get("name") if h.hazard_type_id else None,
                    bbox=h.bbox, visual_evidence=h.visual_evidence, rule_basis=h.rule_basis,
                    evidence_sufficiency=h.evidence_sufficiency, uncertainty_reason=None,
                    reasoning_chain=h.reasoning_chain) for h in stored])
        intake_path = ctx.intake.deposit(image_path=image.path, result=result, note=note)
        ctx.db.add_correction(img_id, note=note, intake_path=intake_path)
        ctx.db.set_image_status(img_id, "corrected_submitted")
        return {"ok": True, "intake_path": intake_path}
    if name == "export_report":
        hazards = ctx.db.get_confirmed_hazards(ctx.session_id)
        path = build_markdown_report(
            session_id=ctx.session_id, hazards=hazards, report_dir=ctx.report_dir,
            object_name_for=lambda oid: (ctx.kg.get_object(oid) or {}).get("name", oid),
            hazard_name_for=lambda hid: (ctx.kg.get_hazard_type(hid) or {}).get("name", hid or ""),
            remediation_for=ctx.kg.remediation_for)
        return {"report_path": path}
    raise ValueError(f"unknown tool: {name}")

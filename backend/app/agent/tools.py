from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.kg.store import KGStore
from app.persistence.db import Database
from app.reports.builder import build_docx_report
from app.vlm.detector import DetectionResult, Hazard as VHazard

if TYPE_CHECKING:
    from app.agent.orchestrator import LoopState


@dataclass
class ToolContext:
    """单次工具调用所需的全部依赖。"""

    db: Database
    kg: KGStore
    standards: Any
    intake: Any
    report_dir: str
    session_id: str


def _owns_image(ctx: "ToolContext", img_id: int) -> bool:
    try:
        return ctx.db.get_image(img_id).session_id == ctx.session_id
    except KeyError:
        return False


TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "finish",
        "description": "完成所有工具查询后调用，提交最终回复。reply 填写向用户展示的完整内容。",
        "parameters": {"type": "object", "properties": {
            "reply": {"type": "string", "description": "向用户显示的完整回复"},
        }, "required": ["reply"]}}},
    {"type": "function", "function": {
        "name": "search_standards",
        "description": "在 JGJ 标准原文(向量库)中语义检索相关条文片段,返回原文与出处。",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
            "top_k": {"type": "integer", "default": 3},
        }, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "get_session_hazards",
        "description": "召回本会话已识别的隐患(多轮记忆)。传 image_id 时返回该图完整字段；不传时返回会话级摘要（长文本截断，最多 limit 条）。",
        "parameters": {"type": "object", "properties": {
            "image_id": {"type": "integer"},
            "limit": {"type": "integer", "description": "会话级查询最多返回条数，默认 20"},
            "status_filter": {"type": "string",
                              "description": "可选过滤：uncertain / confirmed_hazard / safe"},
        }}}},
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
    {"type": "function", "function": {
        "name": "confirm_hazards",
        "description": "当用户确认某张图的识别结果正确时调用,将该图隐患标记为已确认(确认后才会纳入导出报告)。",
        "parameters": {"type": "object", "properties": {
            "image_id": {"type": "integer"}}, "required": ["image_id"]}}},
    {"type": "function", "function": {
        "name": "confirm_hazards_batch",
        "description": "批量确认多张图片的识别结果。image_ids 传具体列表，或 confirm_all=true 确认本会话全部待确认图片。",
        "parameters": {"type": "object", "properties": {
            "image_ids": {"type": "array", "items": {"type": "integer"},
                          "description": "要确认的图片 id 列表"},
            "confirm_all": {"type": "boolean",
                            "description": "true 时确认本会话全部待确认图片"},
        }}}},
    {"type": "function", "function": {
        "name": "query_statistics",
        "description": "统计全库（跨会话）隐患数量，支持按时间段、隐患类型、防护对象过滤，返回总数与分类明细（按频次降序）。用于回答「某天/某段时间多少隐患」「哪类隐患最多/最频繁」等统计类问题。",
        "parameters": {"type": "object", "properties": {
            "date_from": {"type": "string", "description": "起始日期 YYYY-MM-DD（含），不填则不限"},
            "date_to":   {"type": "string", "description": "截止日期 YYYY-MM-DD（含），不填则不限"},
            "hazard_type_id": {"type": "string", "description": "按隐患类型过滤，如 missing_protection"},
            "object_id":      {"type": "string", "description": "按防护对象过滤，如 foundation_pit_edge_protection"},
            "confirmed_only": {"type": "boolean", "description": "仅统计已确认隐患，默认 true"},
        }}}},
]


_KNOWN_TOOLS: frozenset[str] = frozenset(s["function"]["name"] for s in TOOL_SCHEMAS)
_REQUIRED_PARAMS: dict[str, list[str]] = {
    s["function"]["name"]: s["function"]["parameters"].get("required", [])
    for s in TOOL_SCHEMAS
}

# Read-only tools whose results are stable within a session — safe to cache cross-turn.
_CACHEABLE_TOOLS: frozenset[str] = frozenset({"search_standards", "query_statistics"})


class ToolGuard:
    """每轮守卫：校验工具名、必填参数，并对重复调用去重。"""

    def __init__(self, state: "LoopState | None" = None,
                 cross_turn_cache: set[str] | None = None) -> None:
        self._seen: list[str] = []
        # state takes precedence; fall back to legacy kwarg
        self._cross_cache: set[str] | None = (
            state.cross_turn_cache if state is not None else cross_turn_cache
        )

    def check(self, name: str, args: dict[str, Any]) -> str | None:
        """Return None to allow the call, or an error string to reject it."""
        if name not in _KNOWN_TOOLS:
            return f"未知工具：{name}，可用工具：{', '.join(sorted(_KNOWN_TOOLS))}"
        missing = [k for k in _REQUIRED_PARAMS.get(name, [])
                   if k not in args or args[k] is None]
        if missing:
            return f"工具 {name} 缺少必要参数：{', '.join(missing)}"
        key = json.dumps([name, args], sort_keys=True, ensure_ascii=False)
        if key in self._seen:
            return f"工具 {name} 已以相同参数在本轮调用过，跳过重复执行"
        if name in _CACHEABLE_TOOLS and self._cross_cache is not None and key in self._cross_cache:
            return f"工具 {name} 在本会话已以相同参数查询过，结果已缓存，跳过重复查询"
        self._seen.append(key)
        if name in _CACHEABLE_TOOLS and self._cross_cache is not None:
            self._cross_cache.add(key)
        return None


_MAX_TEXT = 100    # 聚合查询中长文本字段的截断长度（字符）


def _trunc(s: str, n: int = _MAX_TEXT) -> str:
    return s if len(s) <= n else s[:n] + "…"


def _hazard_brief(h, full: bool = False) -> dict:
    return {"image_id": h.image_id, "object_id": h.object_id, "status": h.status,
            "hazard_type_id": h.hazard_type_id, "bbox": h.bbox,
            "visual_evidence": h.visual_evidence if full else _trunc(h.visual_evidence),
            "rule_basis": h.rule_basis if full else _trunc(h.rule_basis),
            "evidence_sufficiency": h.evidence_sufficiency, "confirmed": h.confirmed}


def dispatch_tool(name: str, args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """按工具名路由调用并返回结果字典。"""
    if name == "finish":
        return {"done": True, "reply": args.get("reply", "")}
    if name == "search_standards":
        hits = ctx.standards.search(args["query"], top_k=int(args.get("top_k", 3)))
        return {"hits": hits}
    if name == "get_session_hazards":
        img_id = args.get("image_id")
        if img_id:
            if not _owns_image(ctx, int(img_id)):
                return {"hazards": [], "error": f"image {img_id} not in this session"}
            hz = ctx.db.get_hazards(int(img_id))
            return {"hazards": [_hazard_brief(h, full=True) for h in hz]}
        else:
            limit = max(1, min(int(args.get("limit", 20)), 50))
            status_filter = args.get("status_filter")
            all_hz = ctx.db.get_session_hazards(ctx.session_id)
            if status_filter:
                all_hz = [h for h in all_hz if h.status == status_filter]
            return {"total": len(all_hz), "returned": min(len(all_hz), limit),
                    "hazards": [_hazard_brief(h, full=False) for h in all_hz[:limit]]}
    if name == "submit_correction":
        img_id = int(args["image_id"])
        if not _owns_image(ctx, img_id):
            return {"ok": False, "error": f"image {img_id} not in this session"}
        note = args["note"]
        image = ctx.db.get_image(img_id)
        stored = ctx.db.get_hazards(img_id)
        if not stored:
            return {"ok": False, "error": f"no hazards stored for image {img_id}"}
        result = DetectionResult(scene=image.scene, hazards=[
            VHazard(object_id=h.object_id, object_name=(ctx.kg.get_object(h.object_id) or {}).get("name", ""),
                    status=h.status, hazard_type_id=h.hazard_type_id,
                    hazard_type=(ctx.kg.get_hazard_type(h.hazard_type_id) or {}).get("name") if h.hazard_type_id else None,
                    bbox=h.bbox, visual_evidence=h.visual_evidence, rule_basis=h.rule_basis,
                    evidence_sufficiency=h.evidence_sufficiency,
                    uncertainty_reason=h.uncertainty_reason,
                    missing_evidence=h.missing_evidence,
                    reasoning_chain=h.reasoning_chain) for h in stored])
        intake_path = ctx.intake.deposit(image_path=image.path, result=result, note=note)
        ctx.db.add_correction(img_id, note=note, intake_path=intake_path)
        ctx.db.set_image_status(img_id, "corrected_submitted")
        return {"ok": True, "intake_path": intake_path}
    if name == "export_report":
        hazards = ctx.db.get_confirmed_hazards(ctx.session_id)
        path = build_docx_report(
            session_id=ctx.session_id, hazards=hazards, report_dir=ctx.report_dir,
            object_name_for=lambda oid: (ctx.kg.get_object(oid) or {}).get("name", oid),
            hazard_name_for=lambda hid: (ctx.kg.get_hazard_type(hid) or {}).get("name", hid or ""),
            remediation_for=ctx.kg.remediation_for)
        return {"report_path": path}
    if name == "confirm_hazards":
        img_id = int(args["image_id"])
        if not _owns_image(ctx, img_id):
            return {"ok": False, "error": f"image {img_id} not in this session"}
        ctx.db.mark_hazards_confirmed(img_id)
        ctx.db.set_image_status(img_id, "confirmed")
        return {"ok": True, "image_id": img_id}
    if name == "query_statistics":
        return ctx.db.query_hazard_stats(
            date_from=args.get("date_from"),
            date_to=args.get("date_to"),
            hazard_type_id=args.get("hazard_type_id"),
            object_id=args.get("object_id"),
            confirmed_only=bool(args.get("confirmed_only", True)),
        )
    if name == "confirm_hazards_batch":
        if args.get("confirm_all"):
            ids = ctx.db.get_pending_image_ids(ctx.session_id)
        else:
            ids = [int(i) for i in args.get("image_ids", [])]
        ids = [i for i in ids if _owns_image(ctx, i)]
        for img_id in ids:
            ctx.db.mark_hazards_confirmed(img_id)
            ctx.db.set_image_status(img_id, "confirmed")
        return {"ok": True, "confirmed_count": len(ids), "image_ids": ids}
    raise ValueError(f"unknown tool: {name}")

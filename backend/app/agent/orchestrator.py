from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from app.agent.prompts import SYSTEM_PROMPT, render_detection_message
from app.agent.tools import TOOL_SCHEMAS, ToolContext, ToolGuard, dispatch_tool
from app.persistence.db import Database
from app.persistence.models import ToolCallRecord
from app.vlm.detector import DetectionResult

_CTX_PREFIX = "[context] 待确认图片 image_id="
_BATCH_CTX_PREFIX = "[context] 批量上传 image_ids="
_STATUS_LABEL = {"confirmed": "已确认", "corrected_submitted": "已纠错入队"}


def _compress_assistant_msg(img_id: int, status: str, hazards: list) -> str:
    n = sum(1 for h in hazards if h.status == "confirmed_hazard")
    label = _STATUS_LABEL.get(status, status)
    return (f"[图{img_id}·{label}] 共{len(hazards)}条记录，明确隐患{n}处。"
            f"如需详情请调用 get_session_hazards(image_id={img_id})。")


def _compress_system_ctx(img_id: int, status: str) -> str:
    label = _STATUS_LABEL.get(status, status)
    return f"[已处理] image_id={img_id} 状态:{label}"


_MIN_KEEP = 8


def _trunc_result(result: dict, max_chars: int = 200) -> str:
    s = json.dumps(result, ensure_ascii=False)
    return s[:max_chars] + "…" if len(s) > max_chars else s


@dataclass
class LoopState:
    """单次用户消息的Agent循环执行状态。"""

    session_id: str
    max_iter: int
    timeout_seconds: int
    turn_user_msg_id: int | None = None
    messages: list[dict] = field(default_factory=list)
    cross_turn_cache: set[str] = field(default_factory=set)
    tool_records: list = field(default_factory=list)
    iteration: int = 0
    outcome: str = "pending"
    started_at: float = field(default=0.0)
    deadline: float | None = None

    def __post_init__(self) -> None:
        self.started_at = time.monotonic()
        self.deadline = self.started_at + self.timeout_seconds if self.timeout_seconds > 0 else None

    def is_timed_out(self) -> bool:
        return self.deadline is not None and time.monotonic() >= self.deadline

    def has_iterations_left(self) -> bool:
        return self.iteration < self.max_iter


# 进程内跨轮缓存：按 session_id 持有 cross_turn_cache set，供 LoopState 共享。
_session_cross_caches: dict[str, set[str]] = {}


def ingest_image(db: Database, session_id: str, image_path: str, result: DetectionResult) -> int:
    """将VLM识别结果写入数据库并添加初始展示消息。"""
    img_id = db.add_image(session_id, image_path, result.scene)
    db.add_hazards(img_id, [{
        "object_id": h.object_id, "status": h.status, "hazard_type_id": h.hazard_type_id,
        "bbox": h.bbox, "reasoning_chain": h.reasoning_chain, "visual_evidence": h.visual_evidence,
        "rule_basis": h.rule_basis, "evidence_sufficiency": h.evidence_sufficiency,
        "uncertainty_reason": h.uncertainty_reason, "missing_evidence": h.missing_evidence,
    } for h in result.hazards])
    db.add_message(session_id, "assistant", render_detection_message(result))
    db.add_message(session_id, "system", f"{_CTX_PREFIX}{img_id}")
    return img_id


def ingest_batch_images(
    db: Database,
    session_id: str,
    succeeded: "list[tuple[str, DetectionResult]]",
    failed_files: "list[dict]",
) -> dict:
    """将批量VLM识别结果写入数据库并添加汇总展示消息。"""
    image_ids: list[int] = []
    stats: dict[str, int] = {"confirmed_hazard": 0, "uncertain": 0, "safe": 0}

    for path, result in succeeded:
        img_id = db.add_image(session_id, path, result.scene)
        db.add_hazards(img_id, [{
            "object_id": h.object_id, "status": h.status,
            "hazard_type_id": h.hazard_type_id, "bbox": h.bbox,
            "reasoning_chain": h.reasoning_chain, "visual_evidence": h.visual_evidence,
            "rule_basis": h.rule_basis, "evidence_sufficiency": h.evidence_sufficiency,
            "uncertainty_reason": h.uncertainty_reason, "missing_evidence": h.missing_evidence,
        } for h in result.hazards])
        image_ids.append(img_id)
        for h in result.hazards:
            if h.status in stats:
                stats[h.status] += 1

    total = len(succeeded) + len(failed_files)

    if image_ids:
        fail_note = ""
        if failed_files:
            names = "、".join(f["filename"] for f in failed_files[:5])
            if len(failed_files) > 5:
                names += f" 等{len(failed_files) - 5}张"
            fail_note = f"（{len(failed_files)} 张失败：{names}）"
        assistant_msg = (
            f"已完成 {len(succeeded)} 张图识别{fail_note}，共发现：\n\n"
            f"| 状态 | 数量 |\n|---|---|\n"
            f"| 明确隐患 | {stats['confirmed_hazard']} 处 |\n"
            f"| 证据不足 | {stats['uncertain']} 处 |\n"
            f"| 未见明显隐患 | {stats['safe']} 处 |\n\n"
            "如需查看某张图的详细结果，告诉我图片序号或 image_id；\n"
            "输入「全部确认」批量标记已确认，或指定「确认第 1、3、5 张」。"
        )
        db.add_message(session_id, "assistant", assistant_msg)
        db.add_message(session_id, "system",
                       f"{_BATCH_CTX_PREFIX}{','.join(str(i) for i in image_ids)}")
    else:
        assistant_msg = (
            f"批量上传失败：全部 {total} 张图 VLM 识别出错，"
            "未生成任何隐患记录。请检查模型服务或重新上传。"
        )
        db.add_message(session_id, "assistant", assistant_msg)

    return {
        "total": total,
        "succeeded": len(succeeded),
        "failed": len(failed_files),
        "summary": stats,
        "failed_files": failed_files,
        "assistant_message": assistant_msg,
    }


class Orchestrator:
    """驱动LLM工具调用循环，每次请求创建一个实例。"""

    def __init__(self, db: Database, agent_client: Any, agent_model: str,
                 ctx_factory: Callable[[int], ToolContext], max_iterations: int = 5,
                 max_context_chars: int = 80_000, timeout_seconds: int = 30):
        self._db = db
        self._client = agent_client
        self._model = agent_model
        self._ctx_factory = ctx_factory
        self._max_iter = max_iterations
        self._max_context_chars = max_context_chars
        self._timeout_seconds = timeout_seconds

    def handle_message(self, session_id: str, user_text: str) -> str:
        msg_id = self._db.add_message(session_id, "user", user_text)

        if session_id not in _session_cross_caches:
            _session_cross_caches[session_id] = set()
        state = LoopState(session_id=session_id, max_iter=self._max_iter,
                          timeout_seconds=self._timeout_seconds)
        state.turn_user_msg_id = msg_id
        state.cross_turn_cache = _session_cross_caches[session_id]
        state.messages = self._build_messages(session_id)

        ctx = self._ctx_factory(session_id)
        guard = ToolGuard(state=state)

        while state.has_iterations_left():
            if state.is_timed_out():
                state.outcome = "timeout"
                break

            resp = self._client.chat.completions.create(
                model=self._model, messages=state.messages, tools=TOOL_SCHEMAS, temperature=0)
            if not resp.choices:
                fallback = "模型未返回任何结果,请稍后再试。"
                self._db.add_message(session_id, "assistant", fallback)
                state.outcome = "no_tool_calls"
                self._flush_traces(state)
                return fallback
            msg = resp.choices[0].message
            tool_calls = getattr(msg, "tool_calls", None)
            if not tool_calls:
                reply = msg.content or ""
                self._db.add_message(session_id, "assistant", reply)
                state.outcome = "no_tool_calls"
                self._flush_traces(state)
                return reply

            state.messages.append({"role": "assistant", "content": msg.content or "",
                                    "tool_calls": [{"id": tc.id, "type": "function",
                                                    "function": {"name": tc.function.name,
                                                                 "arguments": tc.function.arguments}}
                                                   for tc in tool_calls]})

            for tc in tool_calls:
                t0 = time.monotonic()
                tc_outcome = "ok"
                args: dict = {}
                tool_result: dict = {}
                try:
                    args = json.loads(tc.function.arguments or "{}")
                    err = guard.check(tc.function.name, args)
                    if err:
                        tc_outcome = "guard_blocked"
                        tool_result = {"error": err}
                    else:
                        tool_result = dispatch_tool(tc.function.name, args, ctx)
                        # finish 工具：立即终止
                        if tc.function.name == "finish" and tool_result.get("done"):
                            reply = tool_result.get("reply", "")
                            self._db.add_message(session_id, "assistant", reply)
                            state.outcome = "finish"
                            self._record_tool(state, tc.function.name, args, tool_result, tc_outcome, t0)
                            self._flush_traces(state)
                            return reply
                        # 外部校验：confirm 类工具执行后验证 DB 状态
                        if tc.function.name in ("confirm_hazards", "confirm_hazards_batch") and tool_result.get("ok"):
                            ids = ([args.get("image_id")] if tc.function.name == "confirm_hazards"
                                   else tool_result.get("image_ids", []))
                            unconfirmed = [i for i in ids if i and self._db.get_image(int(i)).status != "confirmed"]
                            if unconfirmed:
                                tool_result["warning"] = f"image_ids {unconfirmed} 状态未变为 confirmed，请重试"
                except Exception as exc:
                    tc_outcome = "error"
                    tool_result = {"error": str(exc)}
                self._record_tool(state, tc.function.name, args, tool_result, tc_outcome, t0)
                state.messages.append({"role": "tool", "tool_call_id": tc.id,
                                       "content": json.dumps(tool_result, ensure_ascii=False)})

            state.iteration += 1

        state.outcome = state.outcome if state.outcome != "pending" else "max_iter"
        fallback = ("处理超时，请稍后重试或换个问法。" if state.outcome == "timeout"
                    else "我已多次尝试调用工具但未能得出最终回答,请换个问法或稍后再试。")
        self._db.add_message(session_id, "assistant", fallback)
        self._flush_traces(state)
        return fallback

    def _record_tool(self, state: LoopState, name: str, args: dict,
                     result: dict, outcome: str, t0: float) -> None:
        duration_ms = (time.monotonic() - t0) * 1000
        rec = ToolCallRecord(name=name, args=args, result_summary=_trunc_result(result),
                             duration_ms=duration_ms, outcome=outcome, iteration=state.iteration)
        state.tool_records.append(rec)
        if state.turn_user_msg_id is not None:
            self._db.add_tool_trace(
                session_id=state.session_id,
                turn_user_msg_id=state.turn_user_msg_id,
                iteration=state.iteration,
                tool_name=name,
                args_json=json.dumps(args, ensure_ascii=False),
                result_summary=rec.result_summary,
                duration_ms=duration_ms,
                outcome=outcome,
                loop_outcome="pending",
            )

    def _flush_traces(self, state: LoopState) -> None:
        self._db.flush_tool_traces(state.session_id, state.outcome)

    def _build_messages(self, session_id: str) -> list[dict[str, Any]]:
        raw = self._db.get_messages(session_id)

        detect_msg: dict[int, int] = {}   # message.id → image_id
        completed: set[int] = set()
        batch_asst_to_ids: dict[int, list[int]] = {}
        batch_ctx_compressed: set[int] = set()
        prev_asst = None
        for m in raw:
            if m.role == "assistant":
                prev_asst = m
            elif m.role == "system" and m.content.startswith(_CTX_PREFIX):
                img_id = int(m.content[len(_CTX_PREFIX):].strip())
                if prev_asst is not None:
                    detect_msg[prev_asst.id] = img_id
                    try:
                        if self._db.get_image(img_id).status in ("confirmed", "corrected_submitted"):
                            completed.add(img_id)
                    except KeyError:
                        pass
                prev_asst = None
            elif m.role == "system" and m.content.startswith(_BATCH_CTX_PREFIX):
                ids_str = m.content[len(_BATCH_CTX_PREFIX):]
                batch_ids = [int(x) for x in ids_str.split(",") if x.strip().isdigit()]
                if prev_asst is not None and batch_ids:
                    try:
                        all_terminal = all(
                            self._db.get_image(i).status in ("confirmed", "corrected_submitted")
                            for i in batch_ids
                        )
                    except KeyError:
                        all_terminal = False
                    if all_terminal:
                        batch_asst_to_ids[prev_asst.id] = batch_ids
                        batch_ctx_compressed.add(m.id)
                prev_asst = None
            else:
                prev_asst = None

        system_parts = [SYSTEM_PROMPT]
        convo: list[dict[str, Any]] = []
        for m in raw:
            if m.role == "system":
                if m.content.startswith(_CTX_PREFIX):
                    img_id = int(m.content[len(_CTX_PREFIX):].strip())
                    if img_id in completed:
                        img = self._db.get_image(img_id)
                        system_parts.append(_compress_system_ctx(img_id, img.status))
                    else:
                        system_parts.append(m.content)
                elif m.content.startswith(_BATCH_CTX_PREFIX):
                    if m.id in batch_ctx_compressed:
                        system_parts.append("[已处理] 批量上传 全部已处理")
                    else:
                        system_parts.append(m.content)
                else:
                    system_parts.append(m.content)
            elif m.role in ("user", "assistant"):
                if m.id in detect_msg and detect_msg[m.id] in completed:
                    img_id = detect_msg[m.id]
                    img = self._db.get_image(img_id)
                    hz = self._db.get_hazards(img_id)
                    convo.append({"role": "assistant",
                                  "content": _compress_assistant_msg(img_id, img.status, hz)})
                elif m.id in batch_asst_to_ids:
                    n = len(batch_asst_to_ids[m.id])
                    convo.append({"role": "assistant",
                                  "content": f"[批量已处理] 共{n}张图片，全部已确认/已纠错。"})
                else:
                    convo.append({"role": m.role, "content": m.content})

        return [{"role": "system", "content": "\n".join(system_parts)}] + self._trim_convo(convo)

    def _trim_convo(self, convo: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self._max_context_chars <= 0:
            return convo
        total = sum(len(m.get("content") or "") for m in convo)
        if total <= self._max_context_chars:
            return convo
        keep_from = max(0, len(convo) - _MIN_KEEP)
        i = 0
        while i < keep_from and total > self._max_context_chars:
            total -= len(convo[i].get("content") or "")
            i += 1
        return convo[i:]

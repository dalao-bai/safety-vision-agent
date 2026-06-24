from __future__ import annotations

import json
from typing import Any, Callable

from app.agent.prompts import SYSTEM_PROMPT, render_detection_message
from app.agent.tools import TOOL_SCHEMAS, ToolContext, ToolGuard, dispatch_tool
from app.persistence.db import Database
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


class Orchestrator:
    def __init__(self, db: Database, agent_client: Any, agent_model: str,
                 ctx_factory: Callable[[int], ToolContext], max_iterations: int = 5):
        self._db = db
        self._client = agent_client
        self._model = agent_model
        self._ctx_factory = ctx_factory
        self._max_iter = max_iterations

    def handle_image(self, session_id: int, image_path: str, result: DetectionResult) -> int:
        img_id = self._db.add_image(session_id, image_path, result.scene)
        self._db.add_hazards(img_id, [{
            "object_id": h.object_id, "status": h.status, "hazard_type_id": h.hazard_type_id,
            "bbox": h.bbox, "reasoning_chain": h.reasoning_chain, "visual_evidence": h.visual_evidence,
            "rule_basis": h.rule_basis, "evidence_sufficiency": h.evidence_sufficiency,
            "uncertainty_reason": h.uncertainty_reason, "missing_evidence": h.missing_evidence,
        } for h in result.hazards])
        message = render_detection_message(result)
        self._db.add_message(session_id, "assistant", message)
        self._db.add_message(session_id, "system", f"[context] 待确认图片 image_id={img_id}")
        return img_id

    def handle_batch_images(
        self,
        session_id: int,
        succeeded: "list[tuple[str, DetectionResult]]",
        failed_files: "list[dict]",
    ) -> dict:
        image_ids: list[int] = []
        stats: dict[str, int] = {"confirmed_hazard": 0, "uncertain": 0, "safe": 0}

        for path, result in succeeded:
            img_id = self._db.add_image(session_id, path, result.scene)
            self._db.add_hazards(img_id, [{
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
                    names += f" 等{len(failed_files)}张"
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
            system_ctx = f"[context] 批量上传 image_ids={','.join(str(i) for i in image_ids)}"
            self._db.add_message(session_id, "assistant", assistant_msg)
            self._db.add_message(session_id, "system", system_ctx)
        else:
            assistant_msg = (
                f"批量上传失败：全部 {total} 张图 VLM 识别出错，"
                "未生成任何隐患记录。请检查模型服务或重新上传。"
            )
            self._db.add_message(session_id, "assistant", assistant_msg)

        return {
            "total": total,
            "succeeded": len(succeeded),
            "failed": len(failed_files),
            "summary": stats,
            "failed_files": failed_files,
            "assistant_message": assistant_msg,
        }

    def handle_message(self, session_id: int, user_text: str) -> str:
        self._db.add_message(session_id, "user", user_text)
        messages = self._build_messages(session_id)
        ctx = self._ctx_factory(session_id)
        guard = ToolGuard()

        for _ in range(self._max_iter):
            resp = self._client.chat.completions.create(
                model=self._model, messages=messages, tools=TOOL_SCHEMAS, temperature=0)
            if not resp.choices:
                fallback = "模型未返回任何结果,请稍后再试。"
                self._db.add_message(session_id, "assistant", fallback)
                return fallback
            msg = resp.choices[0].message
            tool_calls = getattr(msg, "tool_calls", None)
            if not tool_calls:
                reply = msg.content or ""
                self._db.add_message(session_id, "assistant", reply)
                return reply
            messages.append({"role": "assistant", "content": msg.content or "",
                             "tool_calls": [{"id": tc.id, "type": "function",
                                             "function": {"name": tc.function.name,
                                                          "arguments": tc.function.arguments}} for tc in tool_calls]})
            for tc in tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                    err = guard.check(tc.function.name, args)
                    tool_result = {"error": err} if err else dispatch_tool(tc.function.name, args, ctx)
                except Exception as exc:
                    tool_result = {"error": str(exc)}
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": json.dumps(tool_result, ensure_ascii=False)})

        fallback = "我已多次尝试调用工具但未能得出最终回答,请换个问法或稍后再试。"
        self._db.add_message(session_id, "assistant", fallback)
        return fallback

    def _build_messages(self, session_id: int) -> list[dict[str, Any]]:
        raw = self._db.get_messages(session_id)

        # First pass: map each detection-summary assistant message → its image_id,
        # and collect which image_ids are in a terminal state (safe to compress).
        # Detection summary = assistant message immediately before a _CTX_PREFIX system message.
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

        # Second pass: build message list, compressing completed-image entries.
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

        return [{"role": "system", "content": "\n".join(system_parts)}] + convo

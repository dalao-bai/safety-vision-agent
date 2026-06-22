from __future__ import annotations

import json
from typing import Any, Callable

from app.agent.prompts import SYSTEM_PROMPT, render_detection_message
from app.agent.tools import TOOL_SCHEMAS, ToolContext, dispatch_tool
from app.persistence.db import Database
from app.vlm.detector import DetectionResult


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

    def handle_message(self, session_id: int, user_text: str) -> str:
        self._db.add_message(session_id, "user", user_text)
        messages = self._build_messages(session_id)
        ctx = self._ctx_factory(session_id)

        for _ in range(self._max_iter):
            resp = self._client.chat.completions.create(
                model=self._model, messages=messages, tools=TOOL_SCHEMAS, temperature=0)
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
                    result = dispatch_tool(tc.function.name, args, ctx)
                except Exception as exc:
                    result = {"error": str(exc)}
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": json.dumps(result, ensure_ascii=False)})

        fallback = "我已多次尝试调用工具但未能得出最终回答,请换个问法或稍后再试。"
        self._db.add_message(session_id, "assistant", fallback)
        return fallback

    def _build_messages(self, session_id: int) -> list[dict[str, Any]]:
        history = [{"role": "system", "content": SYSTEM_PROMPT}]
        for m in self._db.get_messages(session_id):
            role = m.role if m.role in ("user", "assistant", "system") else "user"
            history.append({"role": role, "content": m.content})
        return history

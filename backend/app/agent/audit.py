import json
import sqlite3
import time
from langchain_core.callbacks import BaseCallbackHandler
from app.db import repositories as repo
from app.models.schemas import ToolCallSummary


class AuditCallbackHandler(BaseCallbackHandler):
    def __init__(self, conn: sqlite3.Connection, conversation_id: str):
        super().__init__()
        self.conn = conn
        self.conversation_id = conversation_id
        self.tool_summaries: list[ToolCallSummary] = []
        self._tool_starts: dict = {}
        self._llm_starts: dict = {}

    def on_tool_start(self, serialized, input_str, run_id, **kwargs):
        try:
            tool_name = serialized.get("name", "unknown")
            input_data = json.loads(input_str) if isinstance(input_str, str) else input_str
            self._tool_starts[str(run_id)] = (tool_name, time.monotonic(), input_data)
        except Exception:
            pass

    def on_tool_end(self, output, run_id, **kwargs):
        try:
            key = str(run_id)
            if key not in self._tool_starts:
                return
            tool_name, start_time, input_data = self._tool_starts.pop(key)
            duration_ms = int((time.monotonic() - start_time) * 1000)
            if isinstance(output, str):
                try:
                    output_as_dict = json.loads(output)
                except Exception:
                    output_as_dict = {"result": output}
            elif isinstance(output, dict):
                output_as_dict = output
            else:
                output_as_dict = {"result": str(output)}
            repo.save_tool_call(
                self.conn,
                self.conversation_id,
                tool_name=tool_name,
                status="success",
                input_data=input_data,
                output_data=output_as_dict,
                error=None,
                duration_ms=duration_ms,
                call_id=key,
            )
            self.tool_summaries.append(
                ToolCallSummary(
                    tool_name=tool_name,
                    status="success",
                    duration_ms=duration_ms,
                )
            )
        except Exception:
            pass

    def on_tool_error(self, error, run_id, **kwargs):
        try:
            key = str(run_id)
            if key not in self._tool_starts:
                return
            tool_name, start_time, input_data = self._tool_starts.pop(key)
            duration_ms = int((time.monotonic() - start_time) * 1000)
            repo.save_tool_call(
                self.conn,
                self.conversation_id,
                tool_name=tool_name,
                status="error",
                input_data=input_data,
                output_data=None,
                error=str(error),
                duration_ms=duration_ms,
                call_id=key,
            )
            self.tool_summaries.append(
                ToolCallSummary(
                    tool_name=tool_name,
                    status="error",
                    duration_ms=duration_ms,
                )
            )
        except Exception:
            pass

    def on_chat_model_start(self, serialized, messages, run_id, tags=None, **kwargs):
        try:
            if "agent-model" in (tags or []):
                self._llm_starts[str(run_id)] = time.monotonic()
        except Exception:
            pass

    def on_llm_end(self, response, run_id, tags=None, **kwargs):
        try:
            key = str(run_id)
            if key not in self._llm_starts:
                return
            start_time = self._llm_starts.pop(key)
            duration_ms = int((time.monotonic() - start_time) * 1000)
            provider_id = None
            if hasattr(response, "llm_output") and response.llm_output:
                provider_id = response.llm_output.get("id")
            repo.save_model_response(
                self.conn,
                self.conversation_id,
                model_role="agent",
                status="success",
                provider_id=provider_id,
                raw_text=None,
                duration_ms=duration_ms,
            )
        except Exception:
            pass

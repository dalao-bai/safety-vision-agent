# v0.2 LangChain/LangGraph 后端重建 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 v0.1 手写的 Agent 编排循环、工具注册、Responses 客户端、VLM 分析器替换为 LangChain v1 / `create_agent`，保留 SQLite 审计表、Pydantic schema、FastAPI 外壳与前端不变。

**Architecture:** LangGraph 作纯编排引擎，不启用 checkpointer。每轮从 SQLite 重建消息历史传入 `create_agent` 构建的无状态 agent。审计经 `BaseCallbackHandler`（agent 模型调用 + 工具调用）+ `analyze_image` 工具内部（VLM 调用 + 结构化结果）写入既有 6 张审计表，审计表是唯一真相源。

**Tech Stack:** langchain 1.3.x, langchain-core 1.4.x, langchain-openai 1.2.x, langgraph 1.2.x；FastAPI；SQLite；Pydantic v2。已验证的本地参考环境：conda `agent`。

---

## 关键已验证事实（来自对已安装源码的内省，非记忆）

- `create_agent` 导入：`from langchain.agents import create_agent`（由 `langchain` 顶层包导出，非 langgraph）。
- 签名关键参数：`model`、`tools`、`system_prompt`、`response_format`、`checkpointer`（本计划不传）。返回 `CompiledStateGraph`。
- 无状态调用：`agent.invoke({"messages": [...]})` → 返回 dict，`result["messages"][-1]` 是最终 `AIMessage`，`.content` 为文本，`.tool_calls` 为工具调用列表。
- `ChatOpenAI(model=..., base_url=..., api_key=..., use_responses_api=True, temperature=0)` 强制走 Responses API。`set_default_openai_client` 不是 LangChain 习惯用法。
- `llm.with_structured_output(Model, method="json_schema")` 默认 `json_schema`；备选 `function_calling` / `json_mode`。与多模态消息可组合。
- v1 图像内容块格式：`{"type": "image", "base64": <b64>, "mime_type": "image/png"}`，经 `use_responses_api` 自动翻译为 Responses 的 `input_image`。用 `HumanMessage(content_blocks=[...])`。
- 工具依赖注入：**闭包**最适合本项目（无状态、每轮重建 agent、注入 DB 连接 + VLM 可调用对象）。
- 有界循环：`config={"recursion_limit": N}`（顶层键，非 configurable），默认 25。超限抛 `from langgraph.errors import GraphRecursionError`。
- 审计回调：`from langchain_core.callbacks import BaseCallbackHandler`。聊天模型结束事件是 **`on_llm_end(response: LLMResult, *, run_id, ...)`**（无 `on_chat_model_end`）。工具事件 `on_tool_start(serialized, input_str, *, run_id, inputs=..., ...)` / `on_tool_end(output, *, run_id, ...)`，用 `run_id` 关联起止算 duration，工具名在 `serialized["name"]`。
- 附加回调：`config={"callbacks": [handler], "recursion_limit": N}`。

---

## 文件结构

| 文件 | 动作 | 职责 |
| --- | --- | --- |
| `backend/requirements.txt` | 改 | 加 langchain 系列依赖，移除对 `openai` 直接依赖的注释说明 |
| `backend/app/services/llm.py` | 新建 | `build_agent_llm()` / `build_vlm_llm()` 工厂：构造两个 `ChatOpenAI` |
| `backend/app/services/vlm_analyzer.py` | 重写 | 用 `with_structured_output` + 多模态消息，返回既有 `AnalyzerOutcome` |
| `backend/app/agent/tools.py` | 重写 | `build_tools(ctx)` 工厂用闭包注入依赖，返回 4 个 `@tool` |
| `backend/app/agent/audit.py` | 新建 | `AuditCallbackHandler(BaseCallbackHandler)` 写 tool_calls + agent model_responses |
| `backend/app/agent/context.py` | 改 | 产出 LangChain 消息（dict 或 Message）而非 Responses input dicts |
| `backend/app/agent/orchestrator.py` | 重写 | `run_turn(...)` 用 `create_agent` + 闭包工具 + 审计回调 + 受控降级 |
| `backend/app/services/responses_client.py` | 删 | 由 `llm.py` + LangChain 取代 |
| `backend/app/agent/prompts.py` | 基本保留 | 系统提示复用；`HAZARD_JSON_SCHEMA` 不再直接用（schema 由 Pydantic 提供） |

**保持不变：** `db/`、`models/schemas.py`、`api/` 路由外壳、`core/config.py`（除非 spike 要求改）、`frontend/`。

---

## Task 0: 端点能力 de-risk spike（必须最先做）

子代理无法验证两件事：你的端点是否真的提供 `/responses`、是否支持严格 `json_schema`。这两点决定整套方案是否成立，必须在重写前用一次性脚本确认，而不是写到一半才发现。

**Files:**
- Create (临时): `backend/spike_endpoint.py`（验证后删除）

- [ ] **Step 1: 选环境并装依赖**

先按 CLAUDE.md 检查 conda 环境，**不要装进 base**。已存在参考环境 `agent`：

Run:
```bash
conda --no-plugins info --envs
```
若 `agent` 环境存在且含 langchain 1.3.x，直接用它；否则创建专用环境：
```bash
conda create -y -n agent-v02 python=3.11 && conda run -n agent-v02 pip install "langchain>=1.3,<2" "langchain-openai>=1.2,<2" "langgraph>=1.2,<2"
```

- [ ] **Step 2: 写 spike 脚本**

```python
# backend/spike_endpoint.py — 一次性验证，验证后删除
import os, base64, pathlib
from pydantic import BaseModel
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

BASE = os.environ["OPENAI_API_BASE_URL"]
KEY = os.environ["OPENAI_API_KEY"]
VLM = os.environ["VLM_MODEL"]
AGENT = os.environ["AGENT_MODEL"]

class Probe(BaseModel):
    summary: str
    count: int

# A) Responses API 文本可达性 + 结构化输出
agent_llm = ChatOpenAI(model=AGENT, base_url=BASE, api_key=KEY,
                       use_responses_api=True, temperature=0)
structured = agent_llm.with_structured_output(Probe, method="json_schema")
try:
    out = structured.invoke([HumanMessage(content="返回 summary='ok' count=3")])
    print("A json_schema OK:", out)
except Exception as e:
    print("A json_schema FAILED:", repr(e))
    # 回退验证
    structured_fc = agent_llm.with_structured_output(Probe, method="function_calling")
    try:
        out = structured_fc.invoke([HumanMessage(content="返回 summary='ok' count=3")])
        print("A function_calling OK:", out)
    except Exception as e2:
        print("A function_calling FAILED:", repr(e2))

# B) VLM 多模态图像输入
img = pathlib.Path("runtime/uploads").glob("*.jpg")
img_path = next(img, None) or next(pathlib.Path("runtime/uploads").glob("*.png"), None)
if img_path:
    b64 = base64.b64encode(img_path.read_bytes()).decode()
    mime = "image/png" if img_path.suffix == ".png" else "image/jpeg"
    vlm_llm = ChatOpenAI(model=VLM, base_url=BASE, api_key=KEY,
                         use_responses_api=True, temperature=0)
    try:
        resp = vlm_llm.invoke([
            SystemMessage(content="用一句话描述这张图。"),
            HumanMessage(content_blocks=[
                {"type": "text", "text": "这是什么?"},
                {"type": "image", "base64": b64, "mime_type": mime},
            ]),
        ])
        print("B vision OK:", resp.content[:80])
    except Exception as e:
        print("B vision FAILED:", repr(e))
else:
    print("B skipped: no sample image in runtime/uploads")
```

- [ ] **Step 3: 运行 spike**

Run:
```bash
cd backend && conda run -n agent python spike_endpoint.py
```
Expected: `A json_schema OK` 与 `B vision OK`。

**决策门:**
- 若 `A json_schema FAILED` 但 `function_calling OK` → 全计划中 `with_structured_output` 统一改用 `method="function_calling"`（记入 Task 2/3）。
- 若 Responses API 调用整体失败（连 A 文本都不通）→ **停止**，回到设计：要么改用 `use_responses_api=False`（Chat Completions），要么换端点。这是设计假设被推翻，需与用户确认，不要擅自继续。
- 若 `B vision FAILED` → 排查图像块格式/模型是否支持视觉，记录后再继续。

- [ ] **Step 4: 删除 spike，提交决策记录**

```bash
cd backend && rm spike_endpoint.py
```
把决策（json_schema 还是 function_calling、Responses 是否可用）写入设计文档的"已知限制"一节并提交：
```bash
git add docs/superpowers/specs/2026-06-08-v02-langgraph-backend-rebuild-design.md
git commit -m "docs: record v0.2 endpoint capability spike results"
```

---

## Task 1: 依赖与项目骨架

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: 更新 requirements**

把 `backend/requirements.txt` 改为（保留既有，追加 langchain 系列；`openai` 仍由 `langchain-openai` 间接需要，保留显式 pin）：
```
fastapi==0.136.3
uvicorn==0.47.0
pydantic==2.13.4
pydantic-settings==2.14.1
python-multipart==0.0.29
openai==2.37.0
langchain>=1.3,<2
langchain-core>=1.4,<2
langchain-openai>=1.2,<2
langgraph>=1.2,<2

# Test dependencies
pytest==9.0.3
httpx==0.28.1
```

- [ ] **Step 2: 安装并冒烟验证导入**

Run:
```bash
cd backend && conda run -n agent pip install -r requirements.txt && conda run -n agent python -c "from langchain.agents import create_agent; from langchain_openai import ChatOpenAI; from langchain_core.callbacks import BaseCallbackHandler; from langgraph.errors import GraphRecursionError; print('imports ok')"
```
Expected: `imports ok`

- [ ] **Step 3: 提交**

```bash
git add backend/requirements.txt
git commit -m "build: add LangChain v1 / LangGraph deps for v0.2"
```

---

## Task 2: LLM 工厂 (`services/llm.py`)

集中构造两个角色的 `ChatOpenAI`，让其余模块依赖稳定的小接口。

**Files:**
- Create: `backend/app/services/llm.py`
- Test: `backend/tests/test_llm_factory.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_llm_factory.py
from app.services.llm import build_agent_llm, build_vlm_llm


def test_build_agent_llm_sets_endpoint_and_responses_api():
    llm = build_agent_llm(base_url="https://x/v1", api_key="k", model="m-agent")
    assert llm.model_name == "m-agent"
    assert str(llm.openai_api_base) == "https://x/v1"
    assert llm.use_responses_api is True


def test_build_vlm_llm_sets_model():
    llm = build_vlm_llm(base_url="https://x/v1", api_key="k", model="m-vlm")
    assert llm.model_name == "m-vlm"
    assert llm.use_responses_api is True
```

- [ ] **Step 2: 运行验证失败**

Run: `cd backend && conda run -n agent pytest tests/test_llm_factory.py -v`
Expected: FAIL（`ModuleNotFoundError: app.services.llm`）

- [ ] **Step 3: 实现**

```python
# backend/app/services/llm.py
"""ChatOpenAI factories for the two model roles (v0.2).

All provider/endpoint wiring lives here so the rest of the app depends on a
small surface. Both roles target the OpenAI-compatible Responses API.
"""
from __future__ import annotations

from langchain_openai import ChatOpenAI


def build_agent_llm(base_url: str, api_key: str, model: str) -> ChatOpenAI:
    """LLM that drives tool calling and writes final answers."""
    return ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=api_key,
        use_responses_api=True,
        temperature=0,
    ).with_config(tags=["agent-model"])


def build_vlm_llm(base_url: str, api_key: str, model: str) -> ChatOpenAI:
    """Vision LLM that analyzes images into structured hazard JSON."""
    return ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=api_key,
        use_responses_api=True,
        temperature=0,
    )
```

注意：`build_agent_llm` 用 `.with_config(tags=["agent-model"])` 给 agent 模型打标签，供审计回调区分 agent 调用与 VLM 调用（见 Task 5）。

- [ ] **Step 4: 运行验证通过**

`.with_config` 返回 `RunnableBinding`，测试断言的是底层属性。若 `with_config` 包裹后 `model_name` 不可直接访问，改测试为构造未包裹版本，或在工厂内拆分。先运行：

Run: `cd backend && conda run -n agent pytest tests/test_llm_factory.py -v`
Expected: PASS。若因 `with_config` 包裹导致属性访问失败，调整 `build_agent_llm` 为先建 `llm` 再 `return llm`（标签改在 orchestrator 用 `agent_llm.with_config(...)` 处加），并相应保留测试。

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/llm.py backend/tests/test_llm_factory.py
git commit -m "feat: add ChatOpenAI factories for agent and VLM roles"
```

---

## Task 3: 重写 VLM 分析器 (`services/vlm_analyzer.py`)

复用既有 `AnalyzerOutcome` 与 `AnalysisResult`，把底层从手写 Responses 客户端换成 `with_structured_output` + 多模态消息。

**Files:**
- Modify: `backend/app/services/vlm_analyzer.py`
- Test: `backend/tests/test_vlm_analyzer.py`（重写）

- [ ] **Step 1: 写失败测试（用桩 LLM）**

```python
# backend/tests/test_vlm_analyzer.py
import base64
from pathlib import Path

import pytest

from app.models.schemas import AnalysisResult
from app.services.vlm_analyzer import analyze_image


class _StubStructured:
    def __init__(self, result): self._result = result
    def invoke(self, messages):
        # capture for assertions
        _StubStructured.last_messages = messages
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _StubLLM:
    def __init__(self, result): self._result = result
    def with_structured_output(self, schema, method="json_schema"):
        _StubLLM.last_method = method
        return _StubStructured(self._result)


@pytest.fixture
def image_file(tmp_path):
    p = tmp_path / "img.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    return p


def test_analyze_image_success_returns_validated_result(image_file):
    expected = AnalysisResult(summary="ok", hazards=[], needs_followup=False)
    outcome = analyze_image(_StubLLM(expected), str(image_file), "image/png", "看看")
    assert outcome.ok is True
    assert outcome.result.summary == "ok"
    # 多模态消息里应含一个 image 内容块，base64 与文件一致
    human = _StubStructured.last_messages[-1]
    blocks = human.content if isinstance(human.content, list) else human.content_blocks
    img_blocks = [b for b in blocks if b.get("type") == "image"]
    assert img_blocks and img_blocks[0]["base64"] == base64.b64encode(image_file.read_bytes()).decode()


def test_analyze_image_llm_error_is_captured(image_file):
    outcome = analyze_image(_StubLLM(RuntimeError("boom")), str(image_file), "image/png", None)
    assert outcome.ok is False
    assert "boom" in outcome.error


def test_analyze_image_unreadable_file_is_captured(tmp_path):
    outcome = analyze_image(_StubLLM(None), str(tmp_path / "missing.png"), "image/png", None)
    assert outcome.ok is False
    assert "failed to read image" in outcome.error
```

- [ ] **Step 2: 运行验证失败**

Run: `cd backend && conda run -n agent pytest tests/test_vlm_analyzer.py -v`
Expected: FAIL（签名不匹配/导入错误）

- [ ] **Step 3: 重写实现**

```python
# backend/app/services/vlm_analyzer.py
"""VLM image analyzer (v0.2 — LangChain).

Reads a stored image, sends it to the VLM via LangChain's structured-output
runnable requesting the hazard schema, and returns a typed outcome. The LLM is
injected (a ChatOpenAI or any object exposing with_structured_output) so tests
can substitute a stub. Raw text / errors are carried for audit persistence by
the caller (the analyze_image tool).
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.agent.prompts import VLM_SYSTEM_PROMPT
from app.models.schemas import AnalysisResult

# 若 Task 0 spike 判定需用 function_calling，把这里改为 "function_calling"。
_STRUCTURED_METHOD = "json_schema"


@dataclass
class AnalyzerOutcome:
    ok: bool
    result: AnalysisResult | None
    raw_text: str | None
    provider_id: str | None
    error: str | None


def analyze_image(
    vlm_llm: Any,
    image_path: str,
    mime_type: str,
    question: str | None = None,
) -> AnalyzerOutcome:
    """Analyze one image and return a typed outcome."""
    from langchain_core.messages import HumanMessage, SystemMessage

    try:
        image_bytes = Path(image_path).read_bytes()
    except OSError as exc:
        return AnalyzerOutcome(False, None, None, None, f"failed to read image: {exc}")

    b64 = base64.b64encode(image_bytes).decode("ascii")
    user_text = question or "请识别这张施工现场照片中的安全隐患。"

    messages = [
        SystemMessage(content=VLM_SYSTEM_PROMPT),
        HumanMessage(content_blocks=[
            {"type": "text", "text": user_text},
            {"type": "image", "base64": b64, "mime_type": mime_type},
        ]),
    ]

    structured = vlm_llm.with_structured_output(AnalysisResult, method=_STRUCTURED_METHOD)
    try:
        result = structured.invoke(messages)
    except ValidationError as exc:
        return AnalyzerOutcome(False, None, None, None, f"VLM output failed schema validation: {exc}")
    except Exception as exc:  # noqa: BLE001 - surface provider/SDK error as audit data
        return AnalyzerOutcome(False, None, None, None, f"VLM API call failed: {exc}")

    # with_structured_output 直接返回校验后的 Pydantic 对象。
    return AnalyzerOutcome(
        ok=True,
        result=result,
        raw_text=result.model_dump_json(),
        provider_id=None,
        error=None,
    )
```

注意：`with_structured_output` 直接返回 Pydantic 对象，省去 v0.1 的手写 JSON 解析步骤。`raw_text` 以校验后结果序列化保存（审计仍有完整内容）；`provider_id` 在结构化模式下不易拿到，置 `None`，符合既有 `AnalyzerOutcome` 可空契约。

- [ ] **Step 4: 运行验证通过**

Run: `cd backend && conda run -n agent pytest tests/test_vlm_analyzer.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/vlm_analyzer.py backend/tests/test_vlm_analyzer.py
git commit -m "feat: rewrite VLM analyzer on LangChain structured output"
```

---

## Task 4: 重写工具 (`agent/tools.py`)

4 个工具用 `@tool` 声明；依赖（DB 连接、VLM LLM、当前 analysis、图像路径）用**闭包**注入，对模型不可见。`analyze_image` 内部调 VLM 并直接落 VLM 审计（`model_responses` + `analysis_results`），避免与 agent 回调重复写。

**Files:**
- Modify: `backend/app/agent/tools.py`（重写）
- Test: `backend/tests/test_agent_tools.py`（重写）

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_agent_tools.py
from dataclasses import dataclass, field

from app.agent.tools import build_tools, ToolDeps
from app.models.schemas import AnalysisResult, Hazard


def _analysis():
    return AnalysisResult(
        summary="s",
        hazards=[
            Hazard(name="临边", location="楼梯口", risk_level="high",
                   basis="无防护", remediation="加护栏", confidence=0.9),
            Hazard(name="积水", location="地面", risk_level="low",
                   basis="少量", remediation="清理", confidence=0.5),
        ],
    )


def _tools_by_name(deps):
    return {t.name: t for t in build_tools(deps)}


def test_rank_risks_orders_by_severity():
    deps = ToolDeps(analysis=_analysis())
    tools = _tools_by_name(deps)
    out = tools["rank_risks"].invoke({})
    assert out["ranked"][0]["name"] == "临边"
    assert out["ranked"][0]["rank"] == 1


def test_explain_basis_filters_by_name():
    deps = ToolDeps(analysis=_analysis())
    tools = _tools_by_name(deps)
    out = tools["explain_basis"].invoke({"hazard_name": "积水"})
    assert len(out["bases"]) == 1 and out["bases"][0]["name"] == "积水"


def test_suggest_remediation_without_analysis_reports_unavailable():
    deps = ToolDeps(analysis=None)
    tools = _tools_by_name(deps)
    out = tools["suggest_remediation"].invoke({})
    assert out["available"] is False


def test_analyze_image_persists_and_updates_deps(monkeypatch):
    from app.services.vlm_analyzer import AnalyzerOutcome
    persisted = {}

    def fake_run_vlm(vlm_llm, path, mime, question):
        return AnalyzerOutcome(True, _analysis(), '{"raw":1}', None, None)

    monkeypatch.setattr("app.agent.tools.run_vlm_analysis", fake_run_vlm)

    deps = ToolDeps(
        analysis=None, image_path="/x.png", image_mime="image/png",
        vlm_llm=object(),
        on_vlm_result=lambda outcome: persisted.setdefault("outcome", outcome),
    )
    tools = _tools_by_name(deps)
    out = tools["analyze_image"].invoke({"question": "看隐患"})
    assert out["available"] is True
    assert out["hazard_count"] == 2
    assert deps.analysis is not None          # 同轮后续工具可用
    assert persisted["outcome"].ok is True     # 审计回调被触发
```

- [ ] **Step 2: 运行验证失败**

Run: `cd backend && conda run -n agent pytest tests/test_agent_tools.py -v`
Expected: FAIL

- [ ] **Step 3: 重写实现**

```python
# backend/app/agent/tools.py
"""Agent tool factory (v0.2 — LangChain @tool + closure DI).

build_tools(deps) returns the four v0.1 tools as LangChain tools. Per-request
dependencies (VLM LLM, current analysis, image, audit hook) ride in ``deps`` via
closure and stay invisible to the model. analyze_image calls the VLM and invokes
deps.on_vlm_result so the orchestrator can persist VLM audit rows.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from langchain_core.tools import tool

from app.models.schemas import AnalysisResult
from app.services.vlm_analyzer import AnalyzerOutcome, analyze_image as run_vlm_analysis

_RISK_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

_NO_ANALYSIS = {
    "available": False,
    "message": "当前对话还没有可用的隐患分析结果,请先上传照片进行分析。",
}


@dataclass
class ToolDeps:
    """Per-request dependencies injected into tools via closure."""
    analysis: AnalysisResult | None = None
    image_path: str | None = None
    image_mime: str | None = None
    vlm_llm: Any | None = None
    user_question: str | None = None
    # Called by analyze_image with the AnalyzerOutcome so the caller persists
    # VLM model_responses + analysis_results.
    on_vlm_result: Callable[[AnalyzerOutcome], None] | None = None


def build_tools(deps: ToolDeps) -> list:
    """Build the four tools bound to the given per-request deps."""

    @tool
    def analyze_image(question: str | None = None) -> dict:
        """分析当前上传的施工现场照片,识别安全隐患并返回结构化结果。首次分析或用户上传新照片时调用。"""
        if not (deps.vlm_llm and deps.image_path and deps.image_mime):
            return {"available": False, "message": "没有可分析的照片,请先上传施工现场照片。"}
        outcome = run_vlm_analysis(
            deps.vlm_llm, deps.image_path, deps.image_mime, question or deps.user_question
        )
        if deps.on_vlm_result:
            deps.on_vlm_result(outcome)
        if not outcome.ok:
            return {"available": False, "message": f"图像分析失败: {outcome.error}"}
        deps.analysis = outcome.result  # 同轮后续工具可读
        r = outcome.result
        return {
            "available": True,
            "summary": r.summary,
            "hazard_count": len(r.hazards),
            "hazards": [h.model_dump(mode="json") for h in r.hazards],
            "needs_followup": r.needs_followup,
            "followup_question": r.followup_question,
        }

    @tool
    def explain_basis(hazard_name: str | None = None) -> dict:
        """解释已识别隐患的判断依据。当用户询问依据、理由或为什么不安全时调用。"""
        if deps.analysis is None:
            return _NO_ANALYSIS
        hazards = deps.analysis.hazards
        if hazard_name:
            hazards = [h for h in hazards if h.name == hazard_name]
            if not hazards:
                return {"available": False, "message": f"未找到名为 {hazard_name!r} 的隐患。"}
        return {"available": True, "bases": [
            {"name": h.name, "location": h.location, "basis": h.basis} for h in hazards
        ]}

    @tool
    def rank_risks() -> dict:
        """按严重程度对已识别的隐患排序。当用户询问哪个最严重或优先级时调用。"""
        if deps.analysis is None:
            return _NO_ANALYSIS
        ranked = sorted(
            deps.analysis.hazards,
            key=lambda h: (_RISK_ORDER.get(h.risk_level.value, 99), -h.confidence),
        )
        return {"available": True, "ranked": [
            {"rank": i + 1, "name": h.name, "risk_level": h.risk_level.value,
             "confidence": h.confidence}
            for i, h in enumerate(ranked)
        ]}

    @tool
    def suggest_remediation(hazard_name: str | None = None) -> dict:
        """针对已识别隐患给出整改建议。当用户询问如何整改、修复或处理时调用。"""
        if deps.analysis is None:
            return _NO_ANALYSIS
        hazards = deps.analysis.hazards
        if hazard_name:
            hazards = [h for h in hazards if h.name == hazard_name]
            if not hazards:
                return {"available": False, "message": f"未找到名为 {hazard_name!r} 的隐患。"}
        return {"available": True, "remediations": [
            {"name": h.name, "remediation": h.remediation} for h in hazards
        ]}

    return [analyze_image, explain_basis, rank_risks, suggest_remediation]
```

- [ ] **Step 4: 运行验证通过**

Run: `cd backend && conda run -n agent pytest tests/test_agent_tools.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/agent/tools.py backend/tests/test_agent_tools.py
git commit -m "feat: rewrite tools as LangChain @tool with closure DI"
```

---

## Task 5: 审计回调 (`agent/audit.py`)

`BaseCallbackHandler` 子类，写 `tool_calls` 与 agent 的 `model_responses`。用 `run_id` 关联起止算 duration；用 `tags` 区分 agent 模型（打了 `agent-model` 标签）与 VLM 调用——VLM 由工具内部经 `on_vlm_result` 落库，回调里跳过，避免重复。

**Files:**
- Create: `backend/app/agent/audit.py`
- Test: `backend/tests/test_agent_audit.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_agent_audit.py
from uuid import uuid4

from app.agent.audit import AuditCallbackHandler


class _Recorder:
    def __init__(self):
        self.tool_calls = []
        self.model_responses = []
    def save_tool_call(self, **kw): self.tool_calls.append(kw)
    def save_model_response(self, **kw): self.model_responses.append(kw)


class _LLMResult:
    def __init__(self, text):
        # mimic LLMResult.generations[0][0].text
        gen = type("G", (), {"text": text, "message": type("M", (), {"content": text})()})()
        self.generations = [[gen]]
        self.llm_output = {"id": "resp_1"}


def test_tool_start_end_records_one_call_with_duration():
    rec = _Recorder()
    h = AuditCallbackHandler(rec, conversation_id="c1")
    rid = uuid4()
    h.on_tool_start({"name": "rank_risks"}, "{}", run_id=rid, inputs={"x": 1})
    h.on_tool_end({"available": True}, run_id=rid)
    assert len(rec.tool_calls) == 1
    call = rec.tool_calls[0]
    assert call["tool_name"] == "rank_risks"
    assert call["status"] == "success"
    assert call["duration_ms"] is not None


def test_on_llm_end_with_agent_tag_records_model_response():
    rec = _Recorder()
    h = AuditCallbackHandler(rec, conversation_id="c1")
    rid = uuid4()
    h.on_llm_end(_LLMResult("最终答案"), run_id=rid, tags=["agent-model"])
    assert len(rec.model_responses) == 1
    assert rec.model_responses[0]["model_role"] == "agent"
    assert rec.model_responses[0]["status"] == "success"


def test_on_llm_end_without_agent_tag_is_skipped():
    rec = _Recorder()
    h = AuditCallbackHandler(rec, conversation_id="c1")
    h.on_llm_end(_LLMResult("vlm raw"), run_id=uuid4(), tags=["vlm-or-untagged"])
    assert rec.model_responses == []
```

- [ ] **Step 2: 运行验证失败**

Run: `cd backend && conda run -n agent pytest tests/test_agent_audit.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

```python
# backend/app/agent/audit.py
"""Audit callback handler (v0.2).

Writes tool_calls and agent-model model_responses as the LangChain agent runs.
VLM model_responses + analysis_results are written separately inside the
analyze_image tool (see tools.ToolDeps.on_vlm_result), so on_llm_end only records
calls tagged 'agent-model' to avoid double-writing the VLM response.
"""
from __future__ import annotations

import time
from typing import Any, Protocol
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult


class AuditSink(Protocol):
    def save_tool_call(self, **kwargs: Any) -> Any: ...
    def save_model_response(self, **kwargs: Any) -> Any: ...


def _extract_text(response: LLMResult) -> str:
    try:
        gen = response.generations[0][0]
        return getattr(gen, "text", None) or getattr(gen.message, "content", "") or ""
    except (IndexError, AttributeError):
        return ""


class AuditCallbackHandler(BaseCallbackHandler):
    def __init__(self, sink: AuditSink, conversation_id: str):
        self._sink = sink
        self._cid = conversation_id
        self._starts: dict[UUID, float] = {}
        self._names: dict[UUID, str] = {}
        self._inputs: dict[UUID, Any] = {}

    def on_tool_start(self, serialized, input_str, *, run_id, **kwargs):
        self._starts[run_id] = time.monotonic()
        self._names[run_id] = (serialized or {}).get("name") or "unknown"
        self._inputs[run_id] = kwargs.get("inputs")

    def on_tool_end(self, output, *, run_id, **kwargs):
        dur = self._duration_ms(run_id)
        self._sink.save_tool_call(
            conversation_id=self._cid,
            tool_name=self._names.pop(run_id, "unknown"),
            status="success",
            input_data=self._inputs.pop(run_id, None),
            output_data=output if isinstance(output, dict) else {"output": str(output)},
            error=None,
            duration_ms=dur,
            call_id=str(run_id),
        )

    def on_tool_error(self, error, *, run_id, **kwargs):
        dur = self._duration_ms(run_id)
        self._sink.save_tool_call(
            conversation_id=self._cid,
            tool_name=self._names.pop(run_id, "unknown"),
            status="error",
            input_data=self._inputs.pop(run_id, None),
            output_data=None,
            error=str(error),
            duration_ms=dur,
            call_id=str(run_id),
        )

    def on_llm_end(self, response: LLMResult, *, run_id, tags=None, **kwargs):
        if not tags or "agent-model" not in tags:
            return  # VLM / untagged calls are audited elsewhere
        provider_id = (response.llm_output or {}).get("id") if response.llm_output else None
        self._sink.save_model_response(
            conversation_id=self._cid,
            model_role="agent",
            status="success",
            provider_id=provider_id,
            raw_text=_extract_text(response),
            error=None,
        )

    def _duration_ms(self, run_id: UUID) -> int | None:
        start = self._starts.pop(run_id, None)
        return int((time.monotonic() - start) * 1000) if start is not None else None
```

- [ ] **Step 4: 运行验证通过**

Run: `cd backend && conda run -n agent pytest tests/test_agent_audit.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/agent/audit.py backend/tests/test_agent_audit.py
git commit -m "feat: add audit callback handler for tool + agent-model calls"
```

---

## Task 6: 调整 context (`agent/context.py`)

产出 LangChain 可用的消息列表（保留"从 SQLite 重建历史"逻辑），并产出 `ToolDeps` 所需字段，替代旧 `ToolContext` 与 Responses input dicts。

**Files:**
- Modify: `backend/app/agent/context.py`
- Test: `backend/tests/test_agent_context.py`（重写）

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_agent_context.py
from app.agent.context import build_context
from app.db import repositories as repo


def test_build_context_returns_messages_and_deps(db_conn):
    cid = repo.create_conversation(db_conn)
    repo.add_message(db_conn, cid, "user", "你好")
    repo.add_uploaded_image(db_conn, cid, "/p.png", "p.png", "image/png", 10)
    loaded = build_context(db_conn, cid, "请分析", vlm_llm=object(), new_image_uploaded=True)
    roles = [m["role"] for m in loaded.messages]
    assert roles[0] == "system"
    assert "user" in roles
    # 新图上传时注入一条提示调用 analyze_image 的 system 消息
    assert any("analyze_image" in m["content"] for m in loaded.messages if m["role"] == "system")
    assert loaded.deps.image_path == "/p.png"
    assert loaded.deps.image_mime == "image/png"
    assert loaded.deps.user_question == "请分析"
```

（`db_conn` fixture 来自既有 `tests/conftest.py`，沿用。）

- [ ] **Step 2: 运行验证失败**

Run: `cd backend && conda run -n agent pytest tests/test_agent_context.py -v`
Expected: FAIL

- [ ] **Step 3: 重写实现**

```python
# backend/app/agent/context.py
"""Conversation context assembly (v0.2).

Rebuilds the message list and per-request ToolDeps from SQLite each turn. No
checkpointer is used; SQLite remains the single source of truth.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from app.agent.prompts import AGENT_SYSTEM_PROMPT
from app.agent.tools import ToolDeps
from app.db import repositories as repo
from app.models.schemas import AnalysisResult

_HISTORY_LIMIT = 20


@dataclass
class LoadedContext:
    messages: list[dict]
    deps: ToolDeps
    analysis: AnalysisResult | None


def build_context(
    conn: sqlite3.Connection,
    conversation_id: str,
    user_message: str,
    vlm_llm: Any,
    new_image_uploaded: bool = False,
) -> LoadedContext:
    raw_analysis = repo.get_latest_analysis(conn, conversation_id)
    analysis = AnalysisResult.model_validate(raw_analysis) if raw_analysis else None

    image_row = repo.get_latest_image(conn, conversation_id)
    image_path = image_row["stored_path"] if image_row else None
    image_mime = image_row["mime_type"] if image_row else None

    messages: list[dict] = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}]
    for m in repo.list_messages(conn, conversation_id)[-_HISTORY_LIMIT:]:
        messages.append({"role": m["role"], "content": m["content"]})

    if new_image_uploaded and image_path:
        messages.append({
            "role": "system",
            "content": "用户在本轮上传了一张新的施工现场照片,尚未分析。请先调用 analyze_image 工具对其进行隐患分析,再回答用户的问题。",
        })

    deps = ToolDeps(
        analysis=analysis,
        image_path=image_path,
        image_mime=image_mime,
        vlm_llm=vlm_llm,
        user_question=user_message,
    )
    return LoadedContext(messages=messages, deps=deps, analysis=analysis)
```

- [ ] **Step 4: 运行验证通过**

Run: `cd backend && conda run -n agent pytest tests/test_agent_context.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/agent/context.py backend/tests/test_agent_context.py
git commit -m "feat: rebuild context as LangChain messages + ToolDeps"
```

---

## Task 7: 重写编排器 (`agent/orchestrator.py`)

用 `create_agent` 装配无状态 agent；附加审计回调；设 `recursion_limit`；捕获 `GraphRecursionError` 与一般异常做受控降级；落 agent error 审计；持久化最终 assistant 消息。保持 `run_turn` 对 API 层的调用契约（返回 `OrchestratorResult`）。

**Files:**
- Modify: `backend/app/agent/orchestrator.py`（重写）
- Test: `backend/tests/test_agent_orchestrator.py`（重写）

- [ ] **Step 1: 写失败测试（桩 agent）**

```python
# backend/tests/test_agent_orchestrator.py
from langchain_core.messages import AIMessage

from app.agent.orchestrator import run_turn
from app.db import repositories as repo


class _FakeAgent:
    """Stub for the compiled agent: returns a preset final message."""
    def __init__(self, text="这是答案", raise_exc=None):
        self._text = text
        self._raise = raise_exc
    def invoke(self, state, config=None):
        if self._raise:
            raise self._raise
        return {"messages": [AIMessage(content=self._text)]}


def test_run_turn_persists_assistant_message(db_conn, monkeypatch):
    cid = repo.create_conversation(db_conn)
    repo.add_message(db_conn, cid, "user", "你好")

    monkeypatch.setattr(
        "app.agent.orchestrator.create_agent",
        lambda **kw: _FakeAgent("你好,我能帮你分析工地照片。"),
    )
    result = run_turn(
        db_conn, cid, "你好", agent_llm=object(), vlm_llm=object(), max_iterations=5,
    )
    assert result.answer == "你好,我能帮你分析工地照片。"
    msgs = repo.list_messages(db_conn, cid)
    assert msgs[-1]["role"] == "assistant"
    assert msgs[-1]["content"] == "你好,我能帮你分析工地照片。"


def test_run_turn_recursion_limit_degrades_gracefully(db_conn, monkeypatch):
    from langgraph.errors import GraphRecursionError
    cid = repo.create_conversation(db_conn)
    repo.add_message(db_conn, cid, "user", "复杂请求")

    monkeypatch.setattr(
        "app.agent.orchestrator.create_agent",
        lambda **kw: _FakeAgent(raise_exc=GraphRecursionError("limit")),
    )
    result = run_turn(db_conn, cid, "复杂请求", agent_llm=object(), vlm_llm=object())
    assert "步骤过多" in result.answer
    responses = repo.list_model_responses(db_conn, cid)
    assert any(r["status"] == "error" for r in responses)


def test_run_turn_model_error_degrades_gracefully(db_conn, monkeypatch):
    cid = repo.create_conversation(db_conn)
    repo.add_message(db_conn, cid, "user", "hi")
    monkeypatch.setattr(
        "app.agent.orchestrator.create_agent",
        lambda **kw: _FakeAgent(raise_exc=RuntimeError("api down")),
    )
    result = run_turn(db_conn, cid, "hi", agent_llm=object(), vlm_llm=object())
    assert "出现错误" in result.answer
```

- [ ] **Step 2: 运行验证失败**

Run: `cd backend && conda run -n agent pytest tests/test_agent_orchestrator.py -v`
Expected: FAIL

- [ ] **Step 3: 重写实现**

```python
# backend/app/agent/orchestrator.py
"""Agent orchestrator (v0.2 — LangChain create_agent).

Assembles a stateless agent per turn from rebuilt context, runs it with an audit
callback and a bounded recursion limit, and degrades gracefully on recursion or
model errors. SQLite audit tables are the single source of truth; no checkpointer.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage
from langgraph.errors import GraphRecursionError

from app.agent.audit import AuditCallbackHandler
from app.agent.context import build_context
from app.agent.prompts import AGENT_SYSTEM_PROMPT
from app.agent.tools import build_tools
from app.db import repositories as repo
from app.models.schemas import AnalysisResult, ToolCallSummary


@dataclass
class OrchestratorResult:
    answer: str
    analysis: AnalysisResult | None
    tool_calls: list[ToolCallSummary] = field(default_factory=list)


def _final_text(result: Any) -> str:
    try:
        msg = result["messages"][-1]
        if isinstance(msg, AIMessage):
            return msg.content if isinstance(msg.content, str) else str(msg.content)
        return getattr(msg, "content", "") or ""
    except (KeyError, IndexError, TypeError):
        return ""


def run_turn(
    conn: sqlite3.Connection,
    conversation_id: str,
    user_message: str,
    agent_llm: Any,
    vlm_llm: Any,
    max_iterations: int = 5,
    new_image_uploaded: bool = False,
) -> OrchestratorResult:
    """Run one bounded agent turn and return the assistant answer.

    The user message must already be persisted by the caller. ``agent_llm`` must
    be tagged 'agent-model' (build_agent_llm does this) so the audit handler can
    distinguish it from the VLM call.
    """
    loaded = build_context(
        conn, conversation_id, user_message, vlm_llm,
        new_image_uploaded=new_image_uploaded,
    )

    # VLM audit: analyze_image calls this with its outcome.
    def _persist_vlm(outcome):
        repo.save_model_response(
            conn, conversation_id, model_role="vlm",
            status="success" if outcome.ok else "error",
            provider_id=outcome.provider_id, raw_text=outcome.raw_text,
            error=outcome.error,
        )
        if outcome.ok and outcome.result:
            image_row = repo.get_latest_image(conn, conversation_id)
            repo.save_analysis_result(
                conn, conversation_id, outcome.result.model_dump(mode="json"),
                image_id=image_row["id"] if image_row else None,
            )

    loaded.deps.on_vlm_result = _persist_vlm

    tools = build_tools(loaded.deps)
    audit = AuditCallbackHandler(repo, conversation_id)

    agent = create_agent(
        model=agent_llm,
        tools=tools,
        system_prompt=AGENT_SYSTEM_PROMPT,
    )

    config = {"callbacks": [audit], "recursion_limit": max_iterations * 2}
    # 历史已含 system+history;create_agent 也会注入 system_prompt,二者皆可。
    # 这里只传 history(不含我们自己的 system),交由 create_agent 注入 system。
    history = [m for m in loaded.messages if m["role"] != "system"]
    injected = [m for m in loaded.messages if m["role"] == "system" and "analyze_image" in m["content"]]
    invoke_messages = history + injected

    try:
        result = agent.invoke({"messages": invoke_messages}, config=config)
    except GraphRecursionError:
        repo.save_model_response(
            conn, conversation_id, model_role="agent", status="error",
            error=f"exceeded recursion limit ({max_iterations * 2})",
        )
        answer = "抱歉,处理这个请求时步骤过多,已停止。请尝试更具体的提问。"
        repo.add_message(conn, conversation_id, "assistant", answer)
        return OrchestratorResult(answer, loaded.deps.analysis, [])
    except Exception as exc:  # noqa: BLE001 - controlled degradation + audit
        repo.save_model_response(
            conn, conversation_id, model_role="agent", status="error", error=str(exc),
        )
        answer = "抱歉,调用模型时出现错误,请稍后重试。"
        repo.add_message(conn, conversation_id, "assistant", answer)
        return OrchestratorResult(answer, loaded.deps.analysis, [])

    answer = _final_text(result) or "(模型未返回文本)"
    repo.add_message(conn, conversation_id, "assistant", answer)
    # loaded.deps.analysis 在 analyze_image 运行后被原地更新为最新结果。
    return OrchestratorResult(answer, loaded.deps.analysis, [])
```

注意：v0.1 在 `OrchestratorResult.tool_calls` 里回传工具摘要给前端；v0.2 工具调用经审计回调入库，最终答案路径不再即时聚合摘要。若前端依赖 `tool_calls` 字段，Task 8 从 `repo.list_tool_calls` 读取本轮记录补齐;若不依赖,保持空列表（`ChatResponse.tool_calls` 默认空）。Task 8 据实接线。

- [ ] **Step 4: 运行验证通过**

Run: `cd backend && conda run -n agent pytest tests/test_agent_orchestrator.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/agent/orchestrator.py backend/tests/test_agent_orchestrator.py
git commit -m "feat: rewrite orchestrator on LangChain create_agent"
```

---

## Task 8: API 接线、清理、全量回归

把 API 依赖注入从旧 `ResponsesClient` 切到 `llm.py` 工厂；删除 `responses_client.py` 及其测试;补齐 `ChatResponse.tool_calls`（若前端需要）；跑全量测试。

**Files:**
- Modify: `backend/app/api/dependencies.py`（按实际改 LLM 注入）
- Modify: `backend/app/api/__init__.py` 或路由（`run_turn` 新签名：传 `agent_llm` / `vlm_llm` 而非 client+model）
- Delete: `backend/app/services/responses_client.py`、`backend/tests/test_responses_client.py`
- Modify: `backend/app/agent/__init__.py`、`backend/app/services/__init__.py`（清理对已删模块的导出）

- [ ] **Step 1: 读 API 层确认调用点**

Run:
```bash
cd backend && grep -rn "ResponsesClient\|responses_client\|run_turn\|ToolContext\|build_context" app/ tests/
```
列出所有引用点,逐一改到新签名。

- [ ] **Step 2: 改依赖注入构造 LLM**

把 `app/api/dependencies.py` 中构造 `ResponsesClient` 的部分改为构造两个 LLM（按该文件既有结构适配；以下为意图示例,以实际函数名为准）：
```python
from app.services.llm import build_agent_llm, build_vlm_llm

def get_agent_llm(settings = Depends(get_settings)):
    return build_agent_llm(settings.openai_api_base_url, settings.openai_api_key, settings.agent_model)

def get_vlm_llm(settings = Depends(get_settings)):
    return build_vlm_llm(settings.openai_api_base_url, settings.openai_api_key, settings.vlm_model)
```

- [ ] **Step 3: 改路由调用 run_turn 新签名**

路由处把 `run_turn(conn, cid, msg, agent_client, agent_model, vlm_client, vlm_model, ...)` 改为 `run_turn(conn, cid, msg, agent_llm=..., vlm_llm=..., max_iterations=settings.max_tool_iterations, new_image_uploaded=...)`。若 `ChatResponse` 需要 `tool_calls`，在路由内本轮结束后：
```python
from app.db import repositories as repo
# run_turn 之后:
tool_rows = repo.list_tool_calls(conn, cid)  # 本对话全部;如需仅本轮,按时间或 id 过滤
```
按既有前端契约决定是否填充;不需要则不填。

- [ ] **Step 4: 删除废弃模块与测试**

```bash
cd backend && git rm app/services/responses_client.py tests/test_responses_client.py
```
然后从 `app/services/__init__.py`、`app/agent/__init__.py` 删除对 `ResponsesClient` / `ToolContext` / 旧 `analyze_image` 签名的导出引用（用 grep 结果定位）。

- [ ] **Step 5: 跑全量测试**

Run: `cd backend && conda run -n agent pytest -v`
Expected: 全绿。若 `test_chat_api.py` / `test_schemas.py` / `test_image_storage.py` / `test_repositories.py` / `test_config.py` 因签名变化失败,按新接口修正断言（这些表/路由语义未变,仅调用面变化）。

- [ ] **Step 6: 前端契约回归（不改前端）**

Run:
```bash
cd frontend && npm test
```
Expected: 通过。`ChatResponse` 字段未减(answer / analysis / conversation_id 保留;tool_calls 默认空或填充),前端无需改动。若前端测试因 tool_calls 变空而失败,在 Step 3 选择填充。

- [ ] **Step 7: 端到端本地冒烟（可选,需真端点）**

Run:
```bash
cd backend && conda run -n agent uvicorn app.main:app --reload
```
另开前端 `npm run dev`,上传图片问"请识别这张图的安全隐患",再追问"哪个隐患最严重?"。确认:答案返回、`analysis` 显示、SQLite 中 `tool_calls`/`model_responses`/`analysis_results` 有本轮记录。

- [ ] **Step 8: 提交**

```bash
git add -A
git commit -m "feat: wire API to LangChain LLMs and remove responses_client"
```

---

## Task 9: 文档与 roadmap 更新

**Files:**
- Modify: `README.md`、`docs/roadmap.md`、`.env.example`（如配置项有增减）

- [ ] **Step 1: 更新 README 的 Stack/How It Works/Project Structure**

把"OpenAI-compatible Responses API 手写客户端"改为"LangChain v1 / `create_agent`（Responses API via ChatOpenAI）"；架构图中 orchestrator 换成 create_agent + 审计回调；Project Structure 增 `services/llm.py`、`agent/audit.py`，去 `services/responses_client.py`。

- [ ] **Step 2: 更新 roadmap 的 v0.2 条目**

把 v0.2 从"Reliability And Error Handling"改记为"框架重建（LangChain v1 / LangGraph）",并注明:人工复核(v0.6)若用 LangGraph `interrupt()` 需届时引入 checkpointer（当前不启用）。

- [ ] **Step 3: 提交**

```bash
git add README.md docs/roadmap.md .env.example
git commit -m "docs: update README and roadmap for v0.2 framework rebuild"
```

---

## Self-Review

**Spec coverage（逐条对设计文档）:**
- 框架=LangGraph/`create_agent` → Task 7 ✓
- 纯编排、不启用 checkpointer → Task 7（不传 checkpointer）✓
- 自控 SQLite 审计、唯一真相源 → Task 5 + Task 7 `_persist_vlm` ✓
- 复用 Pydantic schema 强制结构化 → Task 3 ✓
- 多模态图像输入 → Task 3 ✓
- 4 工具(closure DI 替代 ToolContext) → Task 4 ✓
- 审计映射(tool_calls / agent model_responses 经回调;VLM + analysis_results 经工具内部) → Task 5 + Task 7 ✓
- 有界循环 + 受控降级 → Task 7（recursion_limit + GraphRecursionError/Exception 兜底）✓
- 错误处理(API 错误、schema 失败) → Task 3 + Task 7 ✓
- 保留 FastAPI/前端/DB → Task 8 不改前端、保留表 ✓
- 端点能力风险(Responses/json_schema 未验证) → Task 0 spike ✓
- 已知限制(reasoning_content 不保留) → 设计文档已记,Task 9 README 标注 ✓
- 测试计划(mock 模型、审计断言、4 工具、超限降级) → 各 Task 的 TDD 步骤 ✓

**Placeholder scan:** 无 TBD/TODO。Task 2 Step 4、Task 8 Step 3/Step 6 含"按实际/据实"分支,均给出明确判定条件与命令,非占位。

**Type consistency:** `ToolDeps`（context.py 产出、tools.py 消费、orchestrator 设 `on_vlm_result`）字段一致；`AnalyzerOutcome`（vlm_analyzer 产出、tools 消费、orchestrator `_persist_vlm` 读 `.ok/.result/.raw_text/.provider_id/.error`）一致；`run_turn` 新签名（`agent_llm`/`vlm_llm`）在 orchestrator 定义、test、Task 8 路由调用三处一致；审计 sink 方法名 `save_tool_call`/`save_model_response` 与 `repositories.py` 既有签名一致（含 `input_data`/`output_data`/`call_id`/`duration_ms`）。

**已知需实现时落地的取舍:** `OrchestratorResult.tool_calls` 在 v0.2 默认空，是否回填由 Task 8 Step 3 按前端契约决定——已显式标注,不是遗漏。

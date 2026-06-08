# v0.2 设计:后端用 LangChain v1 / LangGraph 重建

Date: 2026-06-08
Status: 待评审

## 背景与版本重定义

v0.1 是从零搭的工地安全隐患识别 Agent MVP:手写的工具调用循环(`orchestrator.py`)、手写工具注册(`tools.py`)、手写 Responses API 客户端(`responses_client.py`),证明了"上传图 → VLM 结构化隐患 JSON → 追问"这条端到端循环。

roadmap 原定的 v0.2 是"可靠性与错误处理"。本设计**将 v0.2 重定义为「用成熟框架重建后端」**(用户决定),原可靠性内容(重试、错误展示、配置校验)顺延或在重建中顺带吸收。

**用户的核心诉求:用最成熟的解决方案。**

## 范围

- **重写**:整个后端的 Agent 编排层、工具层、模型客户端、VLM 分析器。
- **保留**:SQLite schema + repositories(6 张审计表)、Pydantic 领域 schema、`build_context` 的"每轮从库重建历史"逻辑、FastAPI 路由外壳、前端 React/Vite(v0.2 不动前端)。

## 框架决策

**选 LangGraph 生态(LangChain v1),用其官方 prebuilt `create_agent`。**

- 候选比较中我原推荐 Pydantic AI(v0.1 已是 Pydantic-native),用户选 LangGraph,理由是生态最成熟、且前瞻匹配 roadmap 后续版本(v0.3 多图、v0.6 人工复核、v0.7 整改任务跟踪等有状态/分支工作流)。
- 在 LangChain v1 中,`create_agent` 取代了 `langgraph.prebuilt.create_react_agent`,是官方钦定的标准建 Agent 路径。基于"用最成熟方案"的诉求,采用 `create_agent` 而非手写 `StateGraph`。

### 持久化决策:LangGraph 作纯编排引擎,不启用 checkpointer

- **不启用** checkpointer。所有状态 + 审计仍写入项目自控的 SQLite 表(复用 v0.1 schema)。
- 每轮像 v0.1 一样从 SQLite 重建消息历史传入 agent。审计表是唯一真相源,无双写冗余。
- 这与 `create_agent` 完全兼容:不传 checkpointer → agent 无状态。
- **前瞻提醒(v0.2 不涉及)**:LangGraph 的人工复核 `interrupt()` 依赖 checkpointer。v0.6 人工复核届时需补 checkpointer,或用其他方式实现复核回环。

## 架构

```
React/Vite UI ──> FastAPI 路由(保留)
                      │
                      ▼
              run_turn(重写:create_agent 封装)
                      │
       ┌──────────────┼───────────────────────────┐
       │              │                            │
  build_context   create_agent(ChatOpenAI    AuditCallbackHandler
  (复用,从库重建)  + 4 个 @tool + 无 checkpointer)  (BaseCallbackHandler)
                      │                            │
       ┌──────────────┴───────┐          落 tool_calls / model_responses
       ▼                      ▼
  analyze_image           explain_basis / rank_risks /
  (调 VLM,内部落          suggest_remediation
   analysis_results +     (对已存 AnalysisResult 的确定性变换)
   VLM model_responses)
                      │
                      ▼
              SQLite(6 张审计表,唯一真相源) + runtime/uploads/
```

### 组件职责

**模型接入(替代 `responses_client.py`)**
- `ChatOpenAI(base_url=..., api_key=..., model=..., use_responses_api=True)` 接现有 OpenAI 兼容 Responses 端点(v0.1 已在用,兼容)。
- VLM 强制结构化输出:`vlm_llm.with_structured_output(AnalysisResult)` —— **直接复用 v0.1 的 Pydantic schema**,换框架收益最大、改写最少的链路。
- 多模态:图片以 base64 data-url 作为 message content 传入(沿用 v0.1 的 `image_data_url` 思路)。
- **已知限制**:`ChatOpenAI` 不保留第三方扩展字段(如 `reasoning_content`)。v0.1 未用到这类字段,影响可控;在 README/限制说明中标注。

**Agent 编排(替代 `orchestrator.py`)**
- `create_agent`(LangChain v1)封装在保留签名的 `run_turn(...)` 里,供 FastAPI 路由调用,对上层接口尽量不变。
- 有界循环:用 `create_agent` 的 `recursion_limit` 替代 v0.1 手写的迭代计数。超限的受控降级(返回友好中文提示 + 落 error 审计)在 callback/封装层兜底,不向用户抛异常。
- 不传 checkpointer。

**工具(替代 `tools.py`)**
- 4 个工具用 `@tool` 装饰器声明:`analyze_image`、`explain_basis`、`rank_risks`、`suggest_remediation`。
- 工具签名与逻辑复用 v0.1:后三者是对已存 `AnalysisResult` 的确定性变换(不触发额外模型调用);`analyze_image` 调 VLM。
- 工具依赖(VLM client、DB 连接、当前 analysis)的注入:用 LangChain 工具的依赖注入机制(`InjectedState` / 闭包 / `RunnableConfig`)传入,替代 v0.1 手写的 `ToolContext`。具体机制在实现计划阶段对照 v1 文档定稿。

**审计(新增 `AuditCallbackHandler`,`BaseCallbackHandler` 子类)**
- `on_tool_start`:记开始时间 + 入参。
- `on_tool_end`:记出参 + 算 duration → 写 `tool_calls`。
- `on_chat_model_end`:拿 agent 原始响应 → 写 `model_responses`。
- VLM 的原始响应 + 结构化 `analysis_results`:在 `analyze_image` 工具**内部**落库(VLM 是工具内的独立模型调用,不经 agent 的 callback)。

### 审计表映射(v0.1 → v0.2 写入点)

| 审计表 | v0.1 写入点 | v0.2 写入点 |
|---|---|---|
| `conversations` / `messages` / `uploaded_images` | FastAPI 路由 + repo | 不变(保留) |
| `tool_calls` | orchestrator 循环内 | `AuditCallbackHandler.on_tool_end` |
| `model_responses`(agent) | orchestrator 循环内 | `AuditCallbackHandler.on_chat_model_end` |
| `model_responses`(VLM) | orchestrator | `analyze_image` 工具内部 |
| `analysis_results` | orchestrator | `analyze_image` 工具内部 |

## 错误处理(吸收原 v0.2 可靠性内容)

- 模型/API 调用失败:捕获并落 `model_responses` error,返回受控中文提示,沿用 v0.1 降级风格。
- VLM 输出非法 JSON / schema 不符:`with_structured_output` + 服务端 Pydantic 校验双重保障;失败时保留原始响应入审计。
- 递归/迭代超限:`recursion_limit` 触发时返回友好提示,不抛栈。
- 启动配置校验:保留 v0.1 的 `load_settings` 行为。

## 保留 vs 重写清单

| 保留(几乎不动) | 重写(换成框架) |
|---|---|
| SQLite schema + repositories(6 张审计表) | `orchestrator.py` → `create_agent` + `run_turn` 封装 |
| Pydantic schemas(`AnalysisResult` 等) | `tools.py` → `@tool` + 依赖注入 |
| `build_context`(每轮重建历史) | `responses_client.py` → `ChatOpenAI(use_responses_api=True)` |
| FastAPI 路由外壳、前端 React/Vite | `vlm_analyzer.py` → `with_structured_output(AnalysisResult)` + 新增 `AuditCallbackHandler` |

## 测试计划

- 模型调用 mock:传 fake `ChatOpenAI` / 桩 LLM,无需联网(沿用 v0.1 思路)。
- `AuditCallbackHandler` 写审计表的断言:工具调用、duration、原始响应、错误均落对应表。
- 4 工具流程 + JSON 解析/schema 校验路径覆盖。
- 有界循环超限的受控降级测试。
- 保留并适配 v0.1 现有后端测试中仍适用的部分;被重写模块的旧测试相应替换。

## 依赖

- 新增:`langchain`(v1)、`langchain-openai`、`langgraph`(`create_agent` 所在包按 v1 实际定稿)。
- 移除:对手写 `responses_client` 的直接依赖(`openai` SDK 可能仍被 `langchain-openai` 间接依赖)。
- 安装遵循 CLAUDE.md:不污染 base conda 环境,用专用环境。

## 非目标(v0.2)

- 不动前端。
- 不加 roadmap 后续的新产品功能(多图、规则库、报告、人工复核、整改跟踪)。
- 不启用 checkpointer / 不引入 LangGraph 记忆持久化。
- 不做认证、多用户隔离、生产化(留给 v1.0)。

## 验收标准

1. 后端 Agent 编排、工具、模型接入、VLM 分析全部跑在 LangChain v1 / `create_agent` 上,手写 orchestrator 循环移除。
2. VLM 仍返回经 Pydantic 校验的结构化隐患 JSON(复用 `AnalysisResult`)。
3. 6 张审计表语义不变,经 `AuditCallbackHandler` + 工具内部写入,内容与 v0.1 等价(工具调用、duration、原始 agent/VLM 响应、错误、结构化分析)。
4. 初次图像分析 + 三类追问(依据 / 风险排序 / 整改)端到端可用。
5. 前端不改即可继续工作(API 契约不变)。
6. 本地测试覆盖工具流程、JSON/schema 路径、审计落库、超限降级,且模型调用全 mock、无需联网。
7. 应用可本地启动并完成一次完整流程。

## 待实现计划阶段定稿的开放点

- `create_agent` 在 LangChain v1 的确切包路径与构造签名(实现计划阶段对照官方 v1 文档核实)。
- 工具依赖注入的确切机制(`InjectedState` vs 闭包 vs `RunnableConfig`)。
- `recursion_limit` 与受控降级的精确接线点(callback vs `run_turn` 封装层)。
- `ChatOpenAI` + `use_responses_api=True` 对当前端点多模态图像输入的确切消息格式。

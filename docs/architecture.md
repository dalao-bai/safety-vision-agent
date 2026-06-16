# Agent 架构与功能总览（v0.2 现状）

Date: 2026-06-16
Status: 现状快照（reflects code as-is）

本文件描述 **工地安全隐患识别 Agent 当前已实现的结构与功能**，作为阅读代码与规划新功能的索引。
不含尚在设计中的功能（如「四口五临边」新 schema 与条款报告）。

一句话概括：**多用户、带审计、带三层记忆的对话式工地隐患分析后端**——能看图出结构化隐患、
追问依据/排序/整改、检索规范库、生成 .docx 报告、收集标错样本。

技术栈：FastAPI + SQLite · LangGraph `create_react_agent` · OpenAI 兼容 VLM(Responses API) ·
ChromaDB 语义检索 · JWT 认证 · python-docx · React + Vite 前端。

---

## 一、整体分层架构

```
┌──────────────────────────────────────────────────────────────────────────┐
│ 前端  React + Vite   (frontend/src/)                                       │
│   App.tsx   上传图片+提问 · 对话转录 · 「最新分析」面板 · 工具调用调试折叠   │
│   api.ts    sendChat() → POST /api/chat ;  types.ts 镜像后端 schema         │
└─────────────────────────────────┬──────────────────────────────────────────┘
                                   │  HTTP（Authorization: Bearer <JWT>）
                                   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ FastAPI  (app/main.py)   CORS(localhost:5173) · 启动即校验配置 · /api/health │
│ ─ 路由层 api/routes/ ──────────────────────────────────────────────────────│
│   auth · chat · analyses · regulations · history · annotation · report      │
│ ─ 依赖注入 api/dependencies.py + auth_deps.py ─────────────────────────────  │
│   get_db(每请求连接) · get_current_user(JWT→用户) · get_vlm_client           │
│   get_regulation_store(应用级单例) · get_annotation_conn                     │
└─────────────────────────────────┬──────────────────────────────────────────┘
                                   │  仅 /api/chat 进入 Agent
                                   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ Agent 编排  agent/orchestrator.py  run_turn()      —— LangGraph 驱动        │
│   ① build_context   系统提示 + 第2层偏好记忆 + 滑窗历史(20条/首条保留)        │
│   ② make_tools      7 个 @tool（闭包绑定 conn/user_id/vlm/回调）             │
│   ③ create_react_agent(ChatOpenAI, tools, 系统提示)                         │
│   ④ AuditCallbackHandler  每次 工具/模型 调用 → 落库（行车记录仪）            │
│   异常兜底：超步数 / 调用失败 都返回中文兜底语并记 error                      │
└─────────────────────────────────┬──────────────────────────────────────────┘
                                   ▼
        ┌──────────────── 7 个工具（agent/tools.py）────────────────┐
        │  analyze_image        看图→结构化隐患JSON（调VLM，落库）   │
        │  explain_basis        解释某隐患的判断依据                 │
        │  rank_risks           按 critical>high>med>low 排序        │
        │  suggest_remediation  给整改建议                          │
        │  search_regulations   规范库语义检索（ChromaDB RAG）       │
        │  generate_report      跨对话合规报告（.docx 后台任务）     │
        │  query_history        跨对话隐患统计（按用户）             │
        └────────────────────────────┬──────────────────────────────┘
                                      ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 服务层  app/services/                                                       │
│   responses_client   OpenAI 兼容 Responses API 封装 + embeddings           │
│   vlm_analyzer       图→VLM→强制JSON→schema校验→typed outcome              │
│   regulation_store   ChromaDB+嵌入；解析PDF/docx·切块·检索·删除            │
│   report_generator   python-docx；跨对话汇总；可选条款引用；进程内任务表    │
│   preference_updater  从隐患统计→LLM生成≤100字偏好摘要                      │
│   image_storage      校验(类型/大小)+落盘 runtime/uploads/                  │
│   security           API key 哈希 + JWT 签发/校验                          │
└─────────────────────────────────┬──────────────────────────────────────────┘
                                   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 存储层                                                                      │
│   SQLite  runtime/agent.db   (db/repositories.py, 无 ORM)                   │
│     conversations · messages · uploaded_images · analysis_results          │
│     tool_calls · model_responses          ← 6 张审计表（v0.1）             │
│     users · user_preferences · user_hazard_stats · regulation_files ← v0.2 │
│   ChromaDB  runtime/chroma/   规范向量（"regulations" collection）          │
│   annotation.db  runtime/annotation.db   待标注图片（标错的图）独立库        │
│   文件   runtime/uploads/{图}  ·  runtime/reports/{报告.docx}               │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 二、API 端点（当前全部功能入口）

```
认证   POST   /api/auth/login              用户名+API密钥 → JWT（首登自动注册）

对话   POST   /api/chat                    主端点：消息+可选图 → Agent 一轮
确认   POST   /api/analyses/confirm        逐图确认准/不准（UI直调，不走LLM）

规范   GET    /api/regulations             列出规范文件
       POST   /api/regulations/upload      上传 PDF/docx → 解析切块入向量库
       DELETE /api/regulations/{id}        软删 + 清向量（仅上传者）

历史   GET    /api/history?start&end       本人对话列表 + 隐患统计
标注   GET    /api/annotation              本人待标注记录
       GET    /api/annotation/export       导出未导出记录为 CSV 并标记

报告   POST   /api/report/generate         起后台 .docx 任务 → task_id
       GET    /api/report/status/{id}      轮询状态
       GET    /api/report/download/{id}    下载（越权校验）
健康   GET    /api/health
```

所有受保护端点都经 `get_current_user` 解析 JWT，并按 `user_id` 做数据隔离；规范库全局共享。

---

## 三、Agent 一轮的执行流（run_turn）

```
/api/chat 收到 消息(+可选图)
  → 校验对话归属（复用对话须属本人）
  → 图片校验+落盘(image_storage) → 落 uploaded_images
  → 落 user 消息
  → run_turn():
       build_context  →  make_tools  →  create_react_agent.invoke
       (AuditCallbackHandler 全程记录 tool_calls / model_responses)
  → 取最新 analysis_results
  → 返回 { conversation_id, answer, analysis, tool_calls }
```

要点：
- 模型看不到图片本身，所以"本轮上传了新图"时，系统提示里追加一句"请先调用 analyze_image"。
- `recursion_limit = max_iterations*2 + 2`，并对 LangGraph 的英文截断串做中文兜底。
- 业务工具（规范检索/报告生成）由路由层以回调注入；为 None 时工具优雅降级（返回 available=false）。

---

## 四、三层记忆（跨对话能力）

```
① 对话内记忆   滑动窗口：最近20条 + 永远保留首条（首次分析）；单条>500字截断
② 用户偏好     user_preferences：LLM 生成≤100字摘要 → 注入系统提示（个性化）
                触发：确认全部准确后的后台任务（preference_updater）
③ 隐患统计     user_hazard_stats：(隐患类型,等级) 出现次数累计
                触发：确认某图准确时 upsert
```

---

## 五、两条「反馈闭环」（已存在）

```
用户点「准确」  → 隐患统计 upsert → (全准)触发偏好更新
用户点「不准确」→ 整图+分析写 annotation.db → /api/annotation/export 导出给标注人员
```

> 规划中：把「不准确」这条进一步接到 annotation_pipeline 自动草标（见
> `docs/superpowers/specs/2026-06-16-annotation-feedback-pipeline-integration-design.md`）。

---

## 六、审计：每次模型/工具调用都落库

`AuditCallbackHandler`（agent/audit.py）挂在 LangGraph 执行器上，自动记录：

- `model_responses`：每次调模型一行（role=agent/vlm、provider_id、status、raw_text、耗时）
- `tool_calls`：每次调工具一行（tool_name、input、output、status、耗时）

用途：排查（为何选这个工具、工具返回了啥、哪步报错）、性能分析（每步耗时）、
追溯（VLM 原始输出留底）、以及后续做评估/标注的数据基础。

---

## 七、当前数据模型（注意：这是「旧」通用 schema）

```
AnalysisResult {
  summary,
  hazards: [{ name, location, risk_level(low/medium/high/critical),
              basis, remediation, confidence }],
  needs_followup, followup_question
}
```

后端 `app/models/schemas.py` 与前端 `frontend/src/types.ts` 是同一契约的两侧，须保持一致。

> 演进方向：本通用 schema 计划被「四口五临边」专用 schema（`reasoning_chain` 思维链 /
> `object_bbox` 边界框 / `hazard_type_id` 等）整体取代，由微调模型产出。条款报告功能是新
> schema 的第一块落地（待微调模型就绪后接入分析链）。

---

## 八、配置与测试

- 配置：`app/core/config.py`（pydantic-settings，读仓库根 `.env`）。必填项缺失启动即报错。
  详见 `.env.example`。
- 测试：`backend/tests/`，154 个用例，全部 mock 模型调用、无需联网。
- 本地运行：后端 `uvicorn app.main:app --reload`（:8000）；前端 `npm run dev`（:5173，代理 /api）。

---

## 目录速查

```
backend/app/
  agent/      orchestrator(编排) · context(上下文) · tools(7工具) · prompts · llm · audit
  api/        routes/(7路由) · dependencies · auth_deps
  core/       config
  db/         schema.sql · repositories · sqlite · annotation
  models/     schemas（领域契约）
  services/   image_storage · vlm_analyzer · regulation_store · report_generator
              preference_updater · responses_client · security
frontend/src/ App.tsx · api.ts · types.ts
docs/         requirements · roadmap · plans · architecture(本文件) · superpowers/specs
```

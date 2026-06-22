# 四口五临边交互式隐患问答助手 — 设计文档

- 日期:2026-06-22
- 状态:待用户最终评审
- 范围:后端 API(FastAPI),前端后续迭代

## 1. 背景与目标

已有一个微调的 VLM(以 vLLM 本地部署,暴露 OpenAI 兼容接口),输入工地图片,输出「整图结论 + 隐患列表」的结构化 JSON。每个隐患含 `scene / related_object(object_id) / hazard_type_id / reasoning_chain / object_bbox / visual_evidence / rule_basis / evidence_sufficiency / status` 等字段,与 `知识图谱主文件/four_openings_edges_kg_v2.json`(9 类防护对象、6 类隐患、3 种状态)完全对齐。

本项目围绕该 VLM 构造一个**交互式隐患问答助手**:用户上传图片并多轮提问,助手用 VLM + KG + 标准向量检索给出带证据与标准溯源的解答,并支持识别后的人在回路纠错,把纠错样本沉入既有 `annotation_pipeline` 形成数据飞轮。

### 核心需求(已确认)

| 维度 | 结论 |
|---|---|
| 核心用途 | 交互式隐患问答助手(传图 + 多轮提问,带证据与标准溯源) |
| 核心能力 | VLM 隐患识别(整图结论+隐患列表) + KG 标准溯源问答 |
| 附加能力 | 多轮上下文记忆、整改建议(由 KG `qualified_conditions` 派生)、导出报告(Markdown) |
| 人在回路 | 识别后主动确认;用户说不对 → 追问哪里错 → 记录纠错 → 沉入流水线待处理队列 |
| 不做 | 区域复查/裁剪复检 |
| 形态 | 后端 API(FastAPI),前端后续 |
| 溯源深度 | KG + 标准 OCR 文档向量检索 |
| 持久化 | SQLite 会话持久化,暂不鉴权 |
| 确认粒度 | 整图一次性确认(说不对再追问) |
| 对接方式 | 沉入待处理队列(解耦,agent 不跑流水线、不写母库) |
| VLM 接入 | 本地 vLLM,OpenAI 兼容接口 |
| 报告格式 | Markdown(本轮) |

## 2. 架构(方案 C:识别确定化 + 问答工具循环)

- **识别是确定步骤**:图片上传即触发 VLM 识别,结果作为稳定结构化资产存入会话;识别**不**作为 LLM 工具,避免漏调/重复调。
- **问答是工具循环**:AGENT_MODEL 持小工具集(KG 查询 / 标准检索 / 会话隐患召回 / 提交纠错 / 导出报告),在 `MAX_TOOL_ITERATIONS` 内循环作答。
- 识别可靠且自动 → bbox/状态/reasoning 可被后续多轮稳定引用;问答保持灵活;工具集小、易测。

### 技术栈(纯 Python,不引入 agent 框架)

- **FastAPI**:后端与路由。
- **openai SDK**:统一调本地 vLLM(VLM)与 AGENT_MODEL(均为 OpenAI 兼容接口),tool-calling 用原生能力。
- **chromadb**:向量库(RAG),embeddings 走 OpenAI 兼容 `/embeddings`。
- **SQLite**(`sqlite3` 或 SQLModel):会话持久化。
- **pydantic-settings**:`.env` 配置。
- **工具循环手写**:「调模型 → 解析 tool_calls → 分发 → 回灌结果」自实现,受 `MAX_TOOL_ITERATIONS` 约束;不用 LangChain/LangGraph,保证控制流可控、可测、易调。
- 若未来需要多 agent 编排或频繁切换供应商,再评估 LangGraph;当前范围不需要。

## 3. 模块结构(按单一职责拆分)

```
backend/app/
  main.py                 FastAPI 应用与路由装配
  config.py               读 .env(pydantic-settings)
  api/
    sessions.py           创建/查询会话
    images.py             上传图片 → 触发识别
    messages.py           对话一轮(确认态 / 问答态)
    reports.py            导出报告 + 下载
  agent/
    orchestrator.py       一轮总调度:区分待确认态 vs 问答态;跑工具循环
    tools.py              工具定义与分发
    prompts.py            系统提示词 + 确认/追问模板
  vlm/detector.py         调本地 vLLM(OpenAI 兼容),解析 {scene, hazards[]}
  kg/store.py             载入 KG;按 object_id/hazard_type_id 查询;输出整改条件
  retrieval/standards.py  标准 OCR 文档向量库(chroma)构建与检索
  correction/intake.py    把{图片+VLM草稿+纠错备注}写入流水线待处理队列
  reports/builder.py      由会话内确认隐患生成 Markdown 报告
  persistence/db.py       SQLite 表与访问
  persistence/models.py   数据类
```

每个单元的契约:
- `vlm/detector.py`:输入图片字节/路径 → 输出已解析的 `DetectionResult{scene, hazards[]}`;依赖 vLLM endpoint;调用/解析失败抛明确异常。
- `kg/store.py`:进程内载入 KG JSON;`get_object(object_id)` / `get_hazard_type(id)` / `remediation_for(object_id)`(由 `qualified_conditions` 派生);纯内存只读。
- `retrieval/standards.py`:`build_index()` 与 `search(query, top_k) -> [{text, source}]`;依赖 chroma + EMBEDDING_MODEL。
- `correction/intake.py`:`deposit(image_path, vlm_result, note) -> intake_path`;只写文件,不跑 runner、不写母库。
- `reports/builder.py`:`build(session) -> markdown_path`。
- `persistence/db.py`:会话/消息/图片/隐患/纠错的读写。

## 4. 数据流(三种轮次)

### A. 上传识别轮 `POST /sessions/{id}/images`
1. 校验图片(类型、大小 `MAX_IMAGE_BYTES`,路径限制在 `UPLOAD_DIR` 内,防路径越界)→ 落盘。
2. `detector.detect()` → `{scene, hazards:[...]}`。
3. 持久化图片 + 隐患(状态 `awaiting_confirmation`)。
4. 助手回复:整图结果摘要(逐隐患:对象 / 状态 / 隐患类型 / bbox / 证据)+ 主动一句「以上识别结果是否正确?」;该图进入待确认态。

### B. 确认轮(用户在对话中回复)
- 「正确」→ 隐患置 `confirmed`,转入问答。
- 「不正确」→ 助手追问「哪里不正确?」。
- 用户自由描述错误 → 助手调 `submit_correction`:把 `{image_id, VLM结果快照, 用户纠错备注, 时间}` 落库,并经 `correction.intake.deposit` **沉入流水线待处理队列**;该图置 `corrected_submitted`,回复「已记录并入队」。

确认/纠错的对话由 orchestrator 的 per-image「待确认」状态驱动:当某图待确认时,系统提示词要求模型先解决确认;模型从用户消息判定对/不对,不对且已说明缘由时调用 `submit_correction`。

### C. 问答轮(标准溯源 / 整改)
- 工具循环作答,引用 KG 与标准原文。整改建议由 `query_kg` 返回的 `qualified_conditions` 反推可操作整改项。

## 5. 工具集(仅问答循环使用;识别不在其中)

| 工具 | 作用 |
|---|---|
| `query_kg(object_id?, hazard_type_id?)` | 返回 KG 实体:定义、inspection_scope、`qualified_conditions`(整改依据)、隐患类型、source 引用 |
| `search_standards(query, top_k)` | 向量检索标准 OCR 原文片段,返回条文 + 文件/章节出处 |
| `get_session_hazards(image_id?)` | 召回本会话已识别隐患(多轮记忆) |
| `submit_correction(image_id, note)` | 记录纠错 + 沉入流水线待处理队列 |
| `export_report(scope?)` | 由会话内确认隐患生成 Markdown 报告并返回下载链接 |

## 6. annotation_pipeline 对接契约(解耦,只写不跑)

- 写入独立待处理目录 `runtime/pipeline_intake/`,布局对齐流水线 `--mock-from-json` 输入:
  - 复制图片到 intake image-dir;
  - 写配套 `<sample>.json`:VLM 草稿对象,字段按 `annotation_pipeline/normalize.py` 期望的草稿结构(object_id、status、hazard_type_id、bbox、visual_evidence 等);
  - 用户纠错备注写入 `review_decisions` 草稿的「审核备注」字段,并打 `needs_rerun` 标记。
- Agent **不**调 `runner`、**不**写母库 `annotation_db/`;数据团队事后用 `--serve-review` 浏览器工具复核入库。
- 配套 JSON 的精确字段映射在实现期对照 `normalize.py` / `runner.py` / `api_client.py` 校验后定稿。

## 7. RAG 检索层

本系统采用**双重 grounding**,两者互补:

- **向量 RAG(`search_standards`)**:对标准 OCR 文档做语义检索 + 增强生成,即教科书式 RAG——检索相关条文片段,连同出处塞进上下文供 AGENT_MODEL 引用作答。负责提供**标准原文佐证**。
- **结构化 grounding(`query_kg`)**:按 `object_id` / `hazard_type_id` 直接查 KG 实体,精确、无幻觉(structured retrieval / GraphRAG 的轻量形态,非向量检索)。负责提供**确定的对象-隐患-规则映射与整改条件**。

向量 RAG 实现:
- 由 `知识图谱主文件/标准规范文件/.../ocr/*.md` 及结构化表格切块建 chroma 索引(`EMBEDDING_MODEL` / `CHROMA_DIR`),首启或独立脚本构建。
- `search` 返回片段 + 出处(文件名 + 章节标题)。
- 向量库不可用时降级为 KG-only 作答并明确说明。

## 8. 持久化(SQLite,不鉴权)

| 表 | 关键字段 |
|---|---|
| `sessions` | id, created_at |
| `messages` | id, session_id, role, content, created_at |
| `images` | id, session_id, path, scene, status(awaiting_confirmation/confirmed/corrected_submitted), created_at |
| `hazards` | id, image_id, object_id, status, hazard_type_id, bbox(json), reasoning_chain(json), visual_evidence, rule_basis, evidence_sufficiency, confirmed |
| `corrections` | id, image_id, note, intake_path, created_at |

## 9. 配置(.env)

- 复用现有键:`OPENAI_API_BASE_URL` / `OPENAI_API_KEY` / `AGENT_MODEL` / `EMBEDDING_MODEL` / `CHROMA_DIR` / `UPLOAD_DIR` / `DATABASE_PATH` / `MAX_IMAGE_BYTES` / `MAX_TOOL_ITERATIONS` / `REPORT_DIR`。
- 新增(VLM 本地 vLLM,可与 AGENT 不同 endpoint):`VLM_MODEL`、`VLM_API_BASE_URL`(默认回退 `OPENAI_API_BASE_URL`)、`VLM_API_KEY`(默认回退 `OPENAI_API_KEY`)。
- 新增:`PIPELINE_INTAKE_DIR`(默认 `runtime/pipeline_intake`)。

## 10. 错误处理

- VLM 调用失败 → 返回错误、可重试,不落半成品。
- VLM 输出非法 JSON / 不合 schema → 存原始 + 标记,告知识别失败。
- 图片路径越界防护(沿用旧项目教训);类型/大小校验。
- 工具循环受 `MAX_TOOL_ITERATIONS` 限制。
- 入队失败 → 纠错仍留库,可重试。
- 检索/向量库不可用 → 降级 KG-only 并说明。

## 11. 测试

- 单元:KG 查询与整改派生、字段归一化映射、`intake.deposit` 产出合法流水线格式、报告生成。
- VLM detector:mock 响应(以样例 JSON 为夹具)。
- 检索:小型语料夹具。
- 集成:
  - 上传→识别→确认(对)→问答带引用;
  - 上传→识别→确认(不对)→纠错→入队(校验 intake 目录产物);
  - 导出 Markdown 报告。
- 端到端冒烟:真实 KG 资产 + 一张样例图。

## 12. 不在本轮范围

- 前端 UI(后续迭代)。
- 鉴权/多用户隔离。
- 区域复查/裁剪复检。
- agent 直接运行流水线或写入母数据库。
- docx/PDF 报告(本轮仅 Markdown)。

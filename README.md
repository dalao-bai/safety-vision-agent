# 四口五临边交互式隐患问答助手

围绕一个**微调 VLM(视觉语言模型)** 构建的建筑安全隐患识别与问答 Agent。用户上传工地照片,系统自动识别「四口五临边」类安全隐患,主动与用户确认结果,基于知识图谱与国家标准给出带证据、可溯源的多轮问答与整改建议;当识别有误时,把纠错样本回流到标注流水线,形成**数据飞轮**。

> 「四口」= 楼梯口、电梯井口、预留洞口、通道口;「五临边」= 阳台、屋面、楼层、基坑、跑道/斜道临边。

---

## 目录

- [1. 它解决什么问题](#1-它解决什么问题)
- [2. 系统架构](#2-系统架构)
- [3. 核心数据流](#3-核心数据流)
- [4. 模块说明](#4-模块说明)
- [5. 知识资产](#5-知识资产)
- [6. 工具集（Agent 能力）](#6-工具集agent-能力)
- [7. 数据飞轮：人在回路纠错](#7-数据飞轮人在回路纠错)
- [8. RAG 检索层](#8-rag-检索层)
- [9. API 接口](#9-api-接口)
- [10. 配置](#10-配置)
- [11. 安装与运行](#11-安装与运行)
- [12. 测试](#12-测试)
- [13. 关键设计决策](#13-关键设计决策)
- [14. 目录结构](#14-目录结构)
- [15. 不在本轮范围](#15-不在本轮范围)

---

## 1. 它解决什么问题

工地安全巡检中，识别「四口五临边」防护隐患依赖经验且容易遗漏。本项目把一个**微调好的 VLM**（专门看工地图片、输出结构化隐患判断）包装成一个可对话的 Agent：

- **看得懂**：VLM 输出整图结论 + 隐患列表（对象、隐患类型、bbox、推理链、视觉证据、状态）。
- **说得清**：Agent 对照知识图谱（KG）和 JGJ 国家标准原文，回答「依据是什么」「该怎么整改」，并给出条文出处。
- **会纠错**：识别后主动问「对不对」，用户说不对就追问、记录，并把样本送回标注流水线，让模型越用越准。

VLM 单次输出示例（一个隐患对象）：

```json
{
  "scene": "四口五临边",
  "related_object": "基坑临边防护",
  "object_bbox": [0, 278, 999, 999],
  "hazard_type_id": "missing_protection",
  "hazard_type": "防护缺失",
  "status": "confirmed_hazard",
  "evidence_sufficiency": "sufficient",
  "visual_evidence": "图中可见基坑开挖形成较深临边，坑边及作业面周边未见连续防护设施。",
  "rule_basis": "开挖深度2m及以上……未设置防护栏杆……人员可直接接近坠落边缘。",
  "reasoning_chain": [
    {"step": "observe",     "content": "……"},
    {"step": "locate",      "content": "……"},
    {"step": "match_rule",  "content": "……"},
    {"step": "assess",      "content": "……"}
  ]
}
```

---

## 2. 系统架构

采用**方案 C：识别确定化 + 问答工具循环**。

```
                     ┌──────────────────────────────────────────────┐
   上传图片 ───────► │  POST /sessions/{id}/images                    │
                     │  1) 校验+落盘 → 2) VLM 识别(确定步骤,非工具)  │
                     │  3) 持久化隐患 → 4) 主动确认问句               │
                     └───────────────┬──────────────────────────────┘
                                     │
   多轮对话 ───────► ┌───────────────▼──────────────────────────────┐
   POST .../messages │  Orchestrator：手写工具循环(AGENT_MODEL)      │
                     │  ┌────────────────────────────────────────┐   │
                     │  │ confirm_hazards  submit_correction      │   │
                     │  │ query_kg(+rule_blocks)  search_standards│   │
                     │  │ get_session_hazards     export_report   │   │
                     │  └────────────────────────────────────────┘   │
                     └───┬──────────┬───────────┬──────────┬─────────┘
                         │          │           │          │
                    ┌────▼───┐ ┌────▼─────┐ ┌───▼────┐ ┌───▼────────┐
                    │  KG    │ │ 标准向量 │ │ SQLite │ │ 流水线      │
                    │ Store  │ │ RAG(chroma)│ 持久化 │ │ intake 队列 │
                    └────────┘ └──────────┘ └────────┘ └────────────┘
```

**两条核心原则：**

1. **识别是确定步骤**，不交给 LLM 临场决定是否调用 —— 上传即触发 VLM，结果作为稳定结构化资产入库，bbox/状态/推理链可被后续多轮稳定引用。
2. **问答是工具循环** —— AGENT_MODEL 持一组小工具，在 `MAX_TOOL_ITERATIONS` 内自主决定调哪个工具、何时作答。

**技术栈：** Python 3.11+ · FastAPI · openai SDK（统一调本地 vLLM 与 AGENT_MODEL，均 OpenAI 兼容）· chromadb · SQLite · pydantic-settings · pytest。**不引入 LangChain/LangGraph**，工具循环手写，控制流可控、可测、易调。

---

## 3. 核心数据流

### A. 上传识别轮 `POST /sessions/{id}/images`
1. 校验图片类型与大小（`MAX_IMAGE_BYTES`），按内容 sha1 命名落盘到 `UPLOAD_DIR`（带路径越界防护）。
2. 调本地 vLLM 识别 → 解析为 `DetectionResult{scene, hazards[]}`。
3. 持久化图片与隐患（状态 `awaiting_confirmation`），完整保留 `uncertainty_reason`/`missing_evidence` 等字段。
4. 返回隐患列表 + 一句主动确认：「以上识别结果是否正确？」

### B. 确认轮（用户在对话中回复）
- **「正确」** → Agent 调 `confirm_hazards(image_id)`，该图隐患置 `confirmed`（只有 confirmed 隐患才进入导出报告）。
- **「不正确」** → Agent 追问「具体哪里不正确？」。
- **用户描述错误** → Agent 调 `submit_correction(image_id, note)`：纠错落库 + 经 `intake.deposit` **沉入流水线待处理队列**，该图置 `corrected_submitted`，回复「已记录并入队」。

### C. 问答轮（标准溯源 / 整改）
- Agent 用 `query_kg` / `search_standards` / `get_session_hazards` 取证后作答，引用 KG 与标准原文；整改建议由 KG 的 `qualified_conditions`（合格条件）或 `rule_blocks`（规则块兜底）派生。

---

## 4. 模块说明

| 模块 | 职责 | 关键契约 |
|---|---|---|
| `app/config.py` | 读 `.env`（pydantic-settings） | VLM endpoint 未设时回退共享 OpenAI 配置 |
| `app/vlm/detector.py` | 调本地 vLLM、容错解析输出 | 输出 `DetectionResult`；名→id 映射；非法 JSON 抛 `DetectionError` |
| `app/kg/store.py` | 载入知识图谱 + 规则块 | `get_object` / `get_hazard_type` / `remediation_for` / `rule_blocks_for` |
| `app/retrieval/standards.py` | 标准 OCR 向量库（RAG） | `build(roots)` 建索引；`search(query, top_k)` 返回片段+出处 |
| `app/correction/intake.py` | 纠错样本写入流水线队列 | `deposit(image, result, note)`；只写文件、不跑流水线、不写母库 |
| `app/reports/builder.py` | 生成 Markdown 报告 | 由会话内 `confirmed` 隐患生成；对插值文本做换行清洗 |
| `app/persistence/db.py` | SQLite 持久化 | 线程锁保护；会话/消息/图片/隐患/纠错读写 |
| `app/agent/tools.py` | 6 个工具的 schema 与分发 | 跨会话 `image_id` 鉴权（`_owns_image`） |
| `app/agent/prompts.py` | 系统提示词 + 识别展示模板 | 指导确认/纠错/作答流程 |
| `app/agent/orchestrator.py` | 一轮调度 + 手写工具循环 | 识别确定化；`system` 上下文统一前置；循环上限兜底 |
| `app/api/*` | FastAPI 路由与依赖装配 | sessions / images / messages / reports |

---

## 5. 知识资产

位于 `知识图谱主文件/`（只读资产）：

- **`four_openings_edges_kg_v2.json`** —— 四口五临边视觉隐患识别知识图谱：
  - 9 类防护对象（每个含 `definition`、`inspection_scope`、`qualified_conditions` 合格条件、标准 `source`）；
  - 6 类隐患类型（防护缺失、防护不连续、临时替代、固定不牢、防护门缺失、通行异常）；
  - 3 种状态（明确隐患 / 未见明显隐患 / 证据不足）。
- **`four_openings_edges_rule_blocks.json`** —— 65 条规则块，按对象 + 隐患类型组织，含规则原文、视觉线索、标准溯源。用于补充 `qualified_conditions` 为空的对象（如基坑、阳台临边）的整改依据。
- **`标准规范文件/`** —— JGJ 59-2011 / JGJ 80-2016 标准 PDF、MinerU OCR 结果（`*.md`）、结构化评分表。RAG 检索层从这里建向量索引。

VLM 的输出字段与 KG 实体**完全对齐**（`related_object`→object_id、`hazard_type_id`、`status` 等），这是整个系统能溯源的基础。

---

## 6. 工具集（Agent 能力）

仅问答循环使用；**识别不在工具集内**（是确定步骤）。

| 工具 | 作用 |
|---|---|
| `query_kg(object_id?, hazard_type_id?)` | 查 KG 实体：定义、检查范围、`qualified_conditions`（整改依据）、`rule_blocks`（规则块兜底）、隐患类型、标准出处 |
| `search_standards(query, top_k)` | 向量检索 JGJ 标准原文片段，返回条文 + 文件/章节出处 |
| `get_session_hazards(image_id?)` | 召回本会话已识别隐患（多轮记忆，支持「刚才那张图」指代） |
| `confirm_hazards(image_id)` | 用户确认正确时把该图隐患置 `confirmed`（报告导出前置条件） |
| `submit_correction(image_id, note)` | 记录纠错 + 沉入流水线待处理队列 |
| `export_report(scope?)` | 由会话内已确认隐患生成 Markdown 报告，返回下载路径 |

所有按 `image_id` 操作的工具都会校验该图属于当前会话，拒绝跨会话访问。

---

## 7. 数据飞轮：人在回路纠错

这是本项目区别于「单纯 VLM 推理服务」的核心。识别后 Agent **主动询问**用户结果是否正确：

- 用户说对 → 标记 confirmed，进入问答。
- 用户说不对 → 追问哪里错 → Agent 调 `submit_correction`，把样本**解耦地**投递进既有 `annotation_pipeline` 的待处理队列。

**投递契约（解耦，只写不跑）**，写入 `PIPELINE_INTAKE_DIR/`：

```
runtime/pipeline_intake/
  images/
    <stem>.<ext>          # 原图副本（stem 冲突自动加 _N 后缀，绝不覆盖）
    <stem>.json           # 流水线 --mock-from-json 配套草稿:VLM 草稿对象
                          #   + agent_source + agent_correction_note(纠错备注)
  corrections/
    <stem>.correction.json # 人读上下文:note + original_vlm 完整快照
                          #   (含 reasoning_chain、rule_basis 等飞轮信号)
```

- **Agent 不调 `runner`、不写母库 `annotation_db/`**。数据团队事后用流水线既有工具复核入库：

  ```bash
  python api_annotation_pipeline.py --mock-from-json \
    --image-dir runtime/pipeline_intake/images \
    --rule-blocks 知识图谱主文件/four_openings_edges_rule_blocks.json \
    --output-dir annotation_pipeline_outputs
  python api_annotation_pipeline.py --serve-review --output-dir annotation_pipeline_outputs
  # 浏览器复核 accept/revise 后:
  python api_annotation_pipeline.py --commit-reviewed --append-to-db
  ```

- 配套 JSON 的字段映射由测试用**真实的** `annotation_pipeline.normalize_draft` 硬校验，保证投递的草稿能被流水线直接消费。

---

## 8. RAG 检索层

系统采用**双重 grounding**，两者互补：

- **向量 RAG（`search_standards`）** —— 对标准 OCR 文档做语义检索 + 增强生成（教科书式 RAG）。用 chromadb 建索引，embeddings 走 OpenAI 兼容 `/embeddings`；检索按标题切块，返回条文片段 + 文件/章节出处。负责提供**标准原文佐证**。
- **结构化 grounding（`query_kg`）** —— 按 `object_id`/`hazard_type_id` 直接查 KG 实体，精确、无幻觉（structured retrieval / 轻量 GraphRAG）。负责提供**确定的对象-隐患-规则映射与整改条件**。

向量库不可用时降级为 KG-only 作答。首次运行前需构建索引：

```bash
cd backend && python scripts/build_standards_index.py
```

---

## 9. API 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/sessions` | 创建会话 → `{session_id}` |
| `GET`  | `/sessions/{id}` | 会话消息历史 |
| `POST` | `/sessions/{id}/images` | 上传图片（multipart `file`）→ 触发识别，返回隐患列表 + 确认问句 |
| `POST` | `/sessions/{id}/messages` | 多轮问答 / 确认 / 纠错，body `{"text": "..."}` → `{reply}` |
| `POST` | `/sessions/{id}/report` | 生成 Markdown 报告 → `{report_path}` |
| `GET`  | `/sessions/{id}/report/download` | 下载报告文件 |
| `GET`  | `/health` | 健康检查 |

识别失败（VLM 输出非法）返回 `422`；图片类型不合法 `400`；超出大小上限 `413`；会话不存在 `404`。

---

## 10. 配置

`.env`（参考 `.env.example`）：

| 键 | 说明 |
|---|---|
| `OPENAI_API_BASE_URL` / `OPENAI_API_KEY` | 共享 OpenAI 兼容配置（AGENT_MODEL、embeddings 用） |
| `AGENT_MODEL` | 对话/工具循环模型 |
| `VLM_MODEL` | 本地 vLLM 的微调视觉模型 |
| `VLM_API_BASE_URL` / `VLM_API_KEY` | VLM 独立 endpoint；未设时**回退**共享配置 |
| `EMBEDDING_MODEL` / `CHROMA_DIR` | 向量 RAG |
| `DATABASE_PATH` / `UPLOAD_DIR` / `REPORT_DIR` | 运行目录 |
| `PIPELINE_INTAKE_DIR` | 纠错样本投递目录（默认 `runtime/pipeline_intake`） |
| `MAX_IMAGE_BYTES` / `MAX_TOOL_ITERATIONS` | 上传上限 / 工具循环上限 |

VLM 用 vLLM 本地部署，默认暴露 OpenAI 兼容接口（`/v1/chat/completions`），因此 detector 复用 openai SDK，只是把 base URL 指向本地 vLLM。

---

## 11. 安装与运行

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env        # 按需填写，VLM_API_BASE_URL 指向本地 vLLM

# 构建标准向量库（首次）
python scripts/build_standards_index.py

# 启动
uvicorn app.main:app --reload --port 8000
```

---

## 12. 测试

```bash
cd backend && python -m pytest -q     # 67 passed
```

测试策略：

- **单元**：KG 查询与整改派生、字段归一化、intake 产物、报告生成、工具分发。
- **VLM detector**：用 FakeClient mock 响应（以真实样例 JSON 为夹具），覆盖容错解析（围栏/CRLF/多种顶层形态/非法输入）。
- **检索**：注入确定性 fake embedder，跑真实 chromadb。
- **intake**：用**真实** `annotation_pipeline.normalize_draft` 硬校验投递契约。
- **集成 / 端到端**：上传→识别→确认→导出（验证报告非空）、上传→识别→纠错→入队（验证 intake 产物）、跨会话鉴权。

---

## 13. 关键设计决策

| 决策 | 理由 |
|---|---|
| 识别确定化，不做 LLM 工具 | 识别是事实基础，不该交给 LLM 临场决定是否调用；做成上传即触发保证每图都有稳定结构化资产 |
| 纯 Python 手写工具循环，不用 LangChain | 工具集小、流程确定，框架反而隐藏控制流、增加调试难度与版本风险 |
| 纠错解耦投递，不跑流水线/不写母库 | 复核入库是流水线既有的人工环节；Agent 只投递原料，职责清晰、风险可控 |
| `remediation_for` 诚实返回 qualified_conditions | 基坑/阳台对象的合格条件为空，改由 `rule_blocks` 兜底，避免对核心案例给空整改 |
| 双重 grounding（KG + 向量 RAG） | KG 给确定映射、向量 RAG 给原文佐证，互补降低幻觉 |
| 系统上下文统一前置到首条 system 消息 | 严格 OpenAI/vLLM 端点只允许 system 在 position 0；避免中途 system 被拒 |
| 持久化补 `uncertainty_reason`/`missing_evidence` | 纠错飞轮的关键信号，尤其是对「证据不足」类样本 |

---

## 14. 目录结构

```
.
├── backend/                     后端 API（本项目主体）
│   ├── app/
│   │   ├── config.py            配置
│   │   ├── main.py              FastAPI 装配
│   │   ├── api/                 路由 + 依赖
│   │   ├── agent/               orchestrator / tools / prompts
│   │   ├── vlm/detector.py      VLM 接入与解析
│   │   ├── kg/store.py          知识图谱
│   │   ├── retrieval/standards.py  向量 RAG
│   │   ├── correction/intake.py 纠错投递
│   │   ├── reports/builder.py   报告生成
│   │   └── persistence/         SQLite
│   ├── scripts/build_standards_index.py
│   ├── tests/                   67 个测试
│   └── README.md
├── annotation_pipeline/         数据标注流水线（草标→复核→入母库）
├── 知识图谱主文件/               KG + 规则块 + JGJ 标准资产
└── docs/superpowers/
    ├── specs/  …-design.md      设计文档
    └── plans/  …-agent.md       逐任务实现计划
```

---

## 15. 不在本轮范围

- 前端 UI（后续迭代；本轮为后端 API）。
- 鉴权 / 多用户隔离（已留接口位，工具层已做同会话校验）。
- 区域复查 / 裁剪复检。
- Agent 直接运行流水线或写入母数据库。
- docx / PDF 报告（本轮仅 Markdown）。

---

> 设计与实现细节见 `docs/superpowers/specs/2026-06-22-foe-hazard-qa-agent-design.md`（设计文档）与 `docs/superpowers/plans/2026-06-22-foe-hazard-qa-agent.md`（逐任务实现计划）。

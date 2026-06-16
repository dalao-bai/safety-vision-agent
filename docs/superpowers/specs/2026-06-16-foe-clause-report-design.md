# 设计：四口五临边 VLM 输出 → 条款检索 → 合规报告

Date: 2026-06-16
Status: 待评审

## 背景与动机

上级项目正在**微调一个「四口五临边」施工安全检测 VLM**。该模型的输出是一套全新的结构化 schema
（含 `reasoning_chain` 思维链、`object_bbox` 边界框、`hazard_type_id`、`rule_basis` 等），与当前
agent 在用的旧 `AnalysisResult`（summary + 通用 hazards）完全不同，且**当前代码库无任何地方处理它**
（已 grep 确认）。

用户需求：**根据该 VLM 输出生成一份带官方条款引用的报告**，条款来自
`知识图谱主文件/标准规范文件/`（JGJ 80-2016、JGJ 59-2011 等）。

### 一个 VLM 输出样例（本设计的输入契约依据）

```json
{
  "scene": "四口五临边",
  "reasoning_chain": [
    {"step": "observe",    "content": "图中可见基坑开挖形成较深临边，坑边及作业面周边未见连续的临边防护栏杆…"},
    {"step": "locate",     "content": "定位到基坑临边防护，位于图像横向居中、偏下，横跨大部分画面。"},
    {"step": "match_rule", "content": "对照候选隐患条款：…未设置防护栏杆…据此可判定为防护缺失。"},
    {"step": "assess",     "content": "关键隐患证据在图中清晰可见，证据充分，可下确定判断。"}
  ],
  "related_object": "基坑临边防护",
  "object_bbox": [0, 278, 999, 999],
  "visual_evidence": "图中可见基坑开挖形成较深临边…",
  "rule_basis": "开挖深度2m及以上或图像中可见明显坠落高差的基坑周边未设置防护栏杆…",
  "evidence_sufficiency": "sufficient",
  "uncertainty_reason": null,
  "hazard_type_id": "missing_protection",
  "hazard_type": "防护缺失",
  "status": "confirmed_hazard"
}
```

## 决策摘要（已与用户确认）

| 维度 | 决定 |
|---|---|
| 优先级 | 先做报告功能；标注流水线方案已存档（`2026-06-16-annotation-feedback-pipeline-integration-design.md`），以后再做 |
| 终态方向 | agent **整体迁移**到新 schema，微调模型成为唯一分析器，旧通用 schema 废弃 |
| 本期范围 | 模型**还没好** → 本期**只做「报告 + 条款检索」侧**，消费新 schema，用样例 JSON 即可开发测试；**不碰**现有还能跑的分析链（避免弄坏 agent） |
| 运行形态 | 接进 agent app（新增端点；将来 `analyze_image` 产出新 schema 后喂同一服务函数实现"对话里实时出"） |
| 条款检索 | **混合**：确定性映射(对象+状态+隐患类型→规则块→条文编号) + 按编号取标准全文原文；语义 RAG 仅兜底 |

## 可行性已端到端验证

用上面的样例跑通确定性链路：

```
related_object "基坑临边防护"  →  object_id "foundation_pit_edge_protection"
(object_id, status=confirmed_hazard, hazard_type_id=missing_protection)
   →  唯一命中 rule_blocks 条目  foundation_pit_edge_protection_H1
      └ 该条 rule_text  ==  VLM 输出的 rule_basis（一字不差，证明模型按此规则训练）
      └ source  →  JGJ 59-2011 第3.11.3条 + 表B.13 + JGJ 80-2016 第4.1.1条、第4.3.1条
标准 markdown 内条文行首锚定（"4.1.1…""4.2.1…"），可按编号确定性切出完整官方原文。
```

结论：一个隐患可对应**多部标准多条**；确定性映射比纯语义 RAG 精准，RAG 仅在没命中时兜底。

## 架构与数据流

```
（本期）外部/离线 VLM 输出 JSON
        │
        ▼
POST /api/foe/report   { analyses: [FoeAnalysis...] }      （新增端点，需登录）
        │  create_task → 后台任务（复刻现有 report 三段式）
        ▼
foe_report_generator.generate_foe_report_docx(analyses, retriever, ...)
        │  逐 image → 逐 FoeObject：
        │     clause_retriever.retrieve(obj) ──► [ClauseRef{标准, 条号, 官方原文, 出处}]
        │        ① related_object→object_id   ② 按(对象,状态,隐患)命中 rule_blocks → source
        │        ③ 解析条号 → 标准 markdown 取全文   ④ 兜底：语义 RAG over 标准全文
        ▼
   .docx 报告（标题页 + 逐隐患：思维链/证据/bbox + 引用官方条文原文）
        │
GET /api/foe/report/status/{id}  ·  /download/{id}
        │
   ——（将来）模型 ready：analyze_image 产 FoeAnalysis → 同一 generate 服务 → 对话里实时出——
```

## 组件与文件改动

### 1. 新增 `backend/app/models/foe_schemas.py` — 新 VLM 输出契约

```python
class ReasoningStep(BaseModel):
    step: str          # observe | locate | match_rule | assess
    content: str

class FoeObject(BaseModel):
    related_object: str                 # 中文对象名，映射到 9 类之一
    object_bbox: list[int]              # [x1,y1,x2,y2]，长度=4
    status: str                         # confirmed_hazard | safe | uncertain
    hazard_type_id: str | None = None   # 6 类之一；非 confirmed_hazard 时为 null
    hazard_type: str | None = None
    visual_evidence: str
    rule_basis: str | None = None
    evidence_sufficiency: str | None = None   # sufficient | insufficient
    uncertainty_reason: str | None = None
    reasoning_chain: list[ReasoningStep] = []

class FoeAnalysis(BaseModel):            # 一张图的分析
    image_ref: str | None = None         # 图片路径/标识（用于报告嵌图，可空）
    width: int | None = None
    height: int | None = None
    objects: list[FoeObject] = []
```

> ✅ 已确认：一张图的模型输出为 `{objects:[...]}`（多对象）。`FoeAnalysis.objects` 承载该列表，
> 报告按"一图多隐患"渲染。

### 2. 新增 `backend/app/services/clause_retriever.py` — 混合条款检索

应用级单例（懒加载，类似 `regulation_store`）。加载期：
- 读 `rule_blocks`(list) → 建 `(object_id, status_target, hazard_type_id) → [rule]` 索引；
  从 rule_blocks 自身的 `object_name`/`object_id` 建中↔英映射（**不依赖 annotation_pipeline**，自包含）。
- 解析两部标准 markdown → `{(标准码, 条号): 官方原文}`（条号行首锚定，正则切分）。
- 读 `四口五临边标准引用索引.md` 作为补充条文源（含条文说明、JGJ59 条款）。
- 语义兜底索引：标准全文分块 + `responses_client.embed` 向量化（仅兜底时用）。

```python
class ClauseRef(BaseModel):
    standard_code: str        # 如 "JGJ 80-2016"
    clause_id: str            # 如 "第4.1.1条"
    official_text: str        # 标准原文
    paraphrase: str | None    # rule_blocks 的 rule_text（口径摘要）
    source_raw: str           # 原始 source 串，便于溯源

def retrieve(self, obj: FoeObject) -> list[ClauseRef]: ...
```

retrieve 逻辑：① `related_object`→`object_id`；② 按 (object_id,status,hazard_type_id) 命中 rule_blocks
（并可用 `rule_basis` 精确文本反查作双保险）；③ 从命中条目的 `source` 正则提取 `第X.Y.Z条` 及所属标准；
④ 按编号取标准全文原文（缺失则查索引 md）；⑤ 都没命中 → 语义 RAG 取 top-k。结果按 (标准,条号) 去重。

### 3. 新增 `backend/app/services/foe_report_generator.py` — 新 schema 报告渲染

复用现有 `report_generator.py` 的 python-docx 套路：
- 标题页：场景、生成时间、图数、按 `status`/`hazard_type` 统计。
- 逐图 → 逐 `FoeObject`：对象名、状态(中文)、隐患类型(中文)、**思维链四步**(观察/定位/匹配规则/评估)、
  视觉证据、证据充分性、（uncertain 时）不确定原因；随后列 `retrieve(obj)` 得到的**官方条文原文 + 出处**。
- 图片：`image_ref` 存在且文件在则嵌图；**bbox 画框本期不做**（留待后续，需 Pillow）。
- 复用 `report_generator` 的进程内任务注册表机制（`create_task`/`set_task_done`/`set_task_error`，
  这几个 URL 无关）。⚠️ 但 `get_task()` 内**硬编码** `download_url=/api/report/download/{id}`，FOE 不能直接
  沿用——FOE 的 status 端点须自行拼 `/api/foe/report/download/{id}`（或为 FOE 用独立的小注册表）。

### 4. 新增 `backend/app/api/routes/foe_report.py` — 端点（本期输入接口）

```
POST /api/foe/report            body: { analyses:[FoeAnalysis...], title? } → { task_id }
GET  /api/foe/report/status/{id}
GET  /api/foe/report/download/{id}
```
三段式复刻现有 `report.py`（后台任务 + 轮询 + 越权校验下载）。**现在就能用样例 JSON 测试**；将来
`analyze_image` 产出 `FoeAnalysis` 后调用同一个 `generate_foe_report_docx` 即可在对话里实时出。

### 5. 改 `backend/app/core/config.py` — 资产路径（默认指向已有文件）

- `foe_rule_blocks: str = "知识图谱主文件/four_openings_edges_rule_blocks.json"`
- `foe_kg: str = "知识图谱主文件/four_openings_edges_kg_v2.json"`
- `foe_standards_dir: str = "知识图谱主文件/标准规范文件"`
- `foe_clause_index: str = "知识图谱主文件/标准规范文件/四口五临边标准引用索引.md"`

相对路径相对仓库根解析；报告输出复用 `report_dir`。资产缺失 → 端点返回清晰错误（不静默）。

### 6. 新增 `backend/tests/test_foe_clause_report.py` — 全程离线

## 数据流：一个隐患如何变成报告里的引用

```
FoeObject{related_object:"基坑临边防护", status:"confirmed_hazard", hazard_type_id:"missing_protection"}
  → object_id = foundation_pit_edge_protection
  → rule_blocks 命中 foundation_pit_edge_protection_H1
  → source 解析出: (JGJ 59-2011, 第3.11.3条) · (JGJ 80-2016, 第4.1.1条) · (JGJ 80-2016, 第4.3.1条)
  → 各自从标准 markdown 取官方原文
  → 报告中渲染:
      【JGJ 80-2016 第4.1.1条】坠落高度基准面2m及以上进行临边作业时，应在临空一侧设置防护栏杆…
      【JGJ 80-2016 第4.3.1条】临边作业的防护栏杆应由横杆、立杆及挡脚板组成…
```

## 错误处理与降级

- 资产文件缺失（rule_blocks/标准目录）→ 检索器加载失败时端点返回 422/503 并说明，不静默出空报告。
- 单个隐患没命中确定性条款 → 走语义 RAG；RAG 也无果 → 报告中标注"未匹配到条文，建议人工复核"，
  **不中断整篇报告**（沿用 `report_generator` 缺图/检索失败不中断的风格）。
- 报告生成是后台任务，失败写入任务注册表供 status 查询。

## 安全与隔离

- 端点需登录（`get_current_user`）；下载校验任务归属（复刻 `report.py`，404 不泄露存在性）。
- 标准条款为全局只读资产，不涉用户数据；报告内容来自请求体传入的分析，不跨用户读库。

## 测试与验证

单元测试（用样例 JSON 作夹具，全程无网络）：
1. 样例 JSON 能解析为 `FoeObject`/`FoeAnalysis`。
2. `related_object`→`object_id` 映射正确（基坑临边防护→foundation_pit_edge_protection）。
3. 确定性命中：样例 → `foundation_pit_edge_protection_H1`，source 解析含 JGJ 80-2016 第4.1.1条。
4. 条文原文抽取：用小 markdown 夹具，`第4.1.1条` → 正确正文。
5. `.docx` 生成：含一个样例对象的 `FoeAnalysis` → 文件存在且包含对象名与某条官方原文片段。
6. 端点：`POST /api/foe/report`（样例）→ task_id；status→done；download 返回文件。
   （确定性命中路径不触发 embed；RAG 兜底单测对 embed 打桩。）

端到端验证：`pytest` 全绿（旧 154 项不受影响，新增独立）；手动 `POST /api/foe/report` 传样例 JSON →
轮询 → 下载 .docx，检查条文引用正确。

## 已知限制与假设

- **一张图输出形态**：已确认为 `{objects:[...]}`（多对象）。
- `source` 串为自由文本，条号用正则提取；以索引 md + 语义 RAG 兜底降低漏匹配。
- 报告格式为 `.docx`（与现有一致）；Markdown/PDF 可后续加。
- bbox 画框本期不做。
- 标准资产须存在于 `知识图谱主文件/`；缺失即报错。
- 这是**新 schema 迁移的第一块**；`analyze_image` 换模型、删旧 schema、改前端、迁移旧测试等属终态，
  待微调模型 ready 再做。

## 范围外（本期不做）

- 换分析器 / 接入微调模型 / 删除旧 `AnalysisResult` 链路 / 改前端 / 迁移旧 154 测试。
- bbox 画框、PDF/Markdown 报告格式。
- 标注流水线集成（独立 spec，已存档）。

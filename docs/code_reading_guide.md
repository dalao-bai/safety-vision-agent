# 代码精读指南

按用户操作的执行流阅读。每一步追踪"调用了什么"，读完再继续往下走。

> 各功能流程图见 [flow_diagrams.md](flow_diagrams.md) | 数据格式见 [data_reference.md](data_reference.md)

---

## 流程一：上传一张图片

> 用户从前端选一张基坑照片，点击上传。后端发生了什么？

### 1. `backend/app/main.py` — 入口

服务怎么启动的，挂载了哪些路由。

**读完回答：**
- 挂载了哪 4 个路由模块？
- CORS 是什么策略，生产环境合适吗？
- `create_app()` 和模块级 `app = create_app()` 各有什么用途？

> 上传图片的完整执行链见 [flow_diagrams.md 功能一](flow_diagrams.md#功能一图片上传--vlm-识别)

---

### 2. `backend/app/api/deps.py` — 依赖注入

FastAPI 怎么把数据库、VLM、Agent 等组件传给每个路由函数。

**读完回答：**
- 哪些组件是进程级单例（`@lru_cache`）？哪些是请求级？
- `get_orchestrator` 是怎么把所有依赖组装成一个 Orchestrator 的？
- `KGStore`、`StandardsIndex`、`Detector` 分别在哪里初始化？

> 各组件在执行链中的位置见 [flow_diagrams.md 功能一](flow_diagrams.md#功能一图片上传--vlm-识别)

---

### 3. `backend/app/api/images.py` — 上传端点

请求打进来，先到这里。

**读完回答：**
- 单张上传和批量上传的处理逻辑有何不同？
- 图片文件存到哪个目录？文件名怎么生成的？
- VLM 识别失败时端点返回什么？图片记录还会写入 DB 吗？
- 识别完成后往 DB 写了哪些东西？（images + hazards + messages 各写什么）

> 接口返回的 JSON 结构见 [data_reference.md §2](data_reference.md#2-上传图片接口返回前端收到的)

---

### 4. `backend/app/vlm/detector.py` — VLM 识别

`upload_image` 调了 `detector.detect(path)`，进来看看。

**读完回答：**
- `_VLM_INSTRUCTION_SIMPLE` 和 `_VLM_INSTRUCTION_FULL` 的区别？当前用哪个？
- VLM 返回的 JSON 被 `_extract_hazards` 解析成什么结构？
- `object_id` 缺失时怎么从中文名 `related_object` 还原？（依赖 KGStore）
- `bbox` 字段如何被规范化？
- `DetectionError` 在哪两种情况下会被抛出？

> VLM 返回的原始 JSON 格式及兼容变体见 [data_reference.md §1](data_reference.md#1-vlm-返回的原始-json)

---

### 5. `backend/app/kg/store.py` — 知识图谱（第一次接触）

VLM 识别时用 KG 做中文名→`object_id` 的映射，这里先了解基础结构。

**读完回答：**
- KG 加载了哪两个 JSON 文件？各存什么内容？
- `object_id_for_name` 的模糊匹配逻辑是什么？
- `remediation_for` 返回什么？`object_id_for_name` 的模糊匹配逻辑是什么？

> 防护对象 object_id 与中文名的完整对照表见 [data_reference.md §8](data_reference.md#8-防护对象-object_id-对照表)

---

### 6. `backend/app/persistence/models.py` — 数据结构

识别结果要写库了，先看数据长什么样。

**读完回答：**
- `Hazard` 的 `status` 字段有哪几个值？语义是什么？
- `confirmed` 字段什么时候被置为 True？这对报告生成有什么影响？
- `ImageRecord.status` 从创建到终态经历哪些状态转换？

> 各字段的实际取值和类型见 [data_reference.md §3](data_reference.md#3-hazards-表字段值)，状态转换图见 [data_reference.md §4](data_reference.md#4-images-表状态机)

---

### 7. `backend/app/persistence/db.py` — 数据库读写

识别结果通过这里写入 SQLite。

**读完回答：**
- `add_image` 写入时 status 初始值是什么？在哪里设的？
- `add_hazards` 为什么要对 `bbox` 和 `reasoning_chain` 做 JSON 序列化？
- `_row_to_hazard` 读出来时做了哪些反向转换？
- `_lock` 是什么？为什么需要它？

> hazards 表各字段含义见 [data_reference.md §3](data_reference.md#3-hazards-表字段值)

---

## 流程二：用户发一条消息

> 图片上传完，用户输入"这个隐患怎么整改？"，Agent 怎么处理？

### 8. `backend/app/api/messages.py` — 消息端点

**读完回答：**
- `post_message` 做了什么？它把请求交给谁处理？
- 如果 session 不存在，返回什么？

> 消息端点的返回格式见 [data_reference.md §6](data_reference.md#6-agent-消息端点返回)

---

### 9. `backend/app/agent/prompts.py` — 系统提示词

Agent 每次调用 LLM 时，system prompt 是什么。

**读完回答：**
- `SYSTEM_PROMPT` 给 LLM 定义了什么角色和约束？
- `render_detection_message` 把识别结果渲染成什么格式？为什么需要这一步？

> 识别结果的数据结构见 [data_reference.md §1](data_reference.md#1-vlm-返回的原始-json) 和 [data_reference.md §3](data_reference.md#3-hazards-表字段值)

---

### 10. `backend/app/agent/orchestrator.py` — Agent 循环核心

`handle_message` 是整个 Agent 的主入口，这是最重要的文件。

**读完回答：**
- `LoopState` 管理哪些状态？`outcome` 有哪几个终态？
- LLM 循环的退出条件有哪几种？
- `_build_messages` 里的上下文压缩逻辑：什么条件触发，压缩成什么样子？
- `_trim_convo` 的截断策略是什么？保底保留几条？
- 跨轮缓存 `_session_cross_caches` 存在哪里，生命周期是什么？

> loop_outcome 各终态的含义见 [flow_diagrams.md 功能二](flow_diagrams.md#功能二用户发消息--agent-循环)

---

### 11. `backend/app/agent/tools.py` — 工具定义与执行

LLM 决定调工具，`dispatch_tool` 负责路由到具体实现。

**读完回答：**
- 7 个工具分别解决什么问题？哪些是只读的，哪些有副作用？
- `ToolGuard.check` 按顺序做了哪三层校验？
- `_CACHEABLE_TOOLS` 包含哪几个？为什么这几个可以跨轮缓存？
- `_owns_image` 做了什么？为什么每个写操作工具都要先调它？

> 工具决策参考（用户说什么 → LLM 调什么工具）见 [flow_diagrams.md 附：工具决策参考](flow_diagrams.md#附agent-工具决策参考)

---

### 12. `backend/app/retrieval/standards.py` — RAG 检索

`search_standards` 工具调用这里检索 JGJ 标准原文。

**读完回答：**
- Dense + BM25 + RRF + CrossEncoder 四层管道各自干什么？
- `chunk_markdown` 按什么规则切块？`overlap_chars` 的作用？
- BM25 用字符级分词还是词语级？为什么？
- `_ensure_reranker` 里的 `HF_HUB_OFFLINE=1` 是为了什么？
- BM25 不可用时降级策略是什么？

> 查询失败时的降级路径见 [flow_diagrams.md 功能三](flow_diagrams.md#功能三查询知识图谱--标准条文)

---

## 流程三：确认隐患 + 导出报告

> 用户说"确认这张图"，然后"导出报告"。

### 13. `confirm_hazards` 工具 → `db.mark_hazards_confirmed`

已在 `tools.py` 和 `db.py` 里看到，回答：
- `mark_hazards_confirmed` 做了什么 SQL 操作？
- `confirm_hazards` 执行后的"外部校验"逻辑是什么？为什么需要二次验证？

> 确认后 images.status 的状态转换见 [data_reference.md §4](data_reference.md#4-images-表状态机)

---

### 14. `backend/app/reports/builder.py` — 报告生成

`export_report` 工具最终调这里生成 .docx。

**读完回答：**
- 参数里有哪几个回调函数？为什么用回调而不是直接传 KGStore？
- `rule_basis` 字段缺失时报告里显示什么？
- 报告文件存在哪里？命名规则是什么？
- 如果会话没有已确认隐患，报告里写什么？

> 完整导出流程（从工具调用到文件落盘）见 [flow_diagrams.md 功能六](flow_diagrams.md#功能六导出报告)

---

### 15. `backend/app/api/reports.py` — 下载端点

**读完回答：**
- 这个端点做了什么？它和 `export_report` 工具有什么分工？
- 报告不存在时返回什么？

> 报告生成和下载的完整流程见 [flow_diagrams.md 功能六](flow_diagrams.md#功能六导出报告)

---

## 流程四：用户纠错

> 用户说"这张图识别错了，基坑边缘有护栏的"。

### 16. `backend/app/correction/intake.py` — 纠错飞轮

**读完回答：**
- `deposit` 在磁盘上创建哪几个文件？各自内容是什么？
- `stem` 是怎么生成的？为什么带 UUID 后缀？
- 写入后 DB 里的 `images.status` 会变成什么？

> 两个写出文件的完整 JSON 结构见 [data_reference.md §5](data_reference.md#5-纠错飞轮写入的文件)

---

## 按需查阅

### `backend/app/config.py`

全局配置，第一次看到某个行为不理解时来查。

**关键问题：**
- `vlm_api_base_url` 和 `openai_api_base_url` 什么情况下是同一个？
- `vlm_instruction_mode` 两个值分别对应什么场景？
- `get_settings()` 为什么用 `@lru_cache`？

---

### `backend/scripts/build_standards_index.py`

构建 RAG 向量索引的离线脚本，不是服务运行时的代码。

**关键问题：**
- 索引从哪些源文件构建？
- 重复运行会覆盖还是追加？

---

## 第五轮（可选）：标注流水线

> 独立于后端服务的离线标注工具，用于生产微调数据。

```
annotation_pipeline/rules.py         ← 规则库加载
annotation_pipeline/prompt.py        ← 给 VLM 的提示词如何构建
annotation_pipeline/normalize.py     ← VLM 输出规范化
annotation_pipeline/runner.py        ← 批量标注主流程
annotation_pipeline/api_client.py    ← API 调用 + SSE 解析
annotation_pipeline/review_server.py ← 人工审核 HTTP 工具
annotation_pipeline/cli.py           ← CLI 入口
```

---

## 读代码时随时问自己

1. **输入/输出是什么？** — 这个函数/模块接收什么，返回/产生什么
2. **它依赖谁？** — import 了什么，为什么
3. **谁调用它？** — 在执行链里处于什么位置

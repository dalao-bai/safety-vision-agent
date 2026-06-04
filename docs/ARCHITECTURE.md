# 架构说明

## 总体原则

当前 MVP 优先简单可跑：不用 ORM、迁移框架、队列、Redis、PostgreSQL 和复杂 Agent 框架。复杂度放在业务能力上：多轮记忆、工具调用、证据融合、整改、报告和标注反哺。

```text
Vite React 控制台
-> FastAPI
-> 轻量 Agent 状态机
-> SQLite 业务记忆
-> VLM / YOLO / 规则 / 融合 / 整改 / 报告 / 标注工具
```

微调 VLM 不是对话大脑，而是视觉隐患识别工具。Agent 负责意图判断、历史检索、工具选择、证据融合、追问、整改和报告。

## 后端模块

```text
backend/app/agent/
  graph.py      简单状态机执行器
  nodes.py      加载记忆、分类、分析、依据、整改、报告、持久化节点
  router.py     确定性意图路由
  tools.py      统一工具包装和 tool_calls 记录
  state.py      JSON 可序列化 Agent state

backend/app/db/
  schema.sql    应用业务表
  sqlite.py     SQLite 连接和初始化
  repositories.py 轻量 repository
```

会话、消息、图片、工具调用、分析结果、复核、整改、标注样本和训练候选都保存在应用自有 SQLite 表中。

## 多轮流程

```text
用户消息
-> 加载会话记忆和最新融合结果
-> 分类：新图分析 / 依据追问 / 整改 / 报告 / 补证 / 记忆回答
-> 必要时调用工具
-> 保存用户消息、助手回答、工具调用和业务结果
-> 返回 answer、conversation_id、latest_analysis_id、fused_result、tool_calls、artifacts
```

## 标注反哺闭环

```text
FusedResult
-> AnnotationSample draft
-> Human review accept / revise / reject
-> accepted_records images.jsonl / objects.jsonl
-> TrainingCandidate
```

`backend/app/annotation_pipeline/` 保留四口五临边 API 辅助标注流水线代码，后续可扩展批量草标和审核台。

## 后续可选升级

- 如果状态分支继续复杂，再引入 LangGraph。
- 如果并发和耗时指标证明需要，再引入队列。
- 如果进入生产多用户数据，再考虑 PostgreSQL。
- 如果需要跨历史案例语义检索，再引入向量库。

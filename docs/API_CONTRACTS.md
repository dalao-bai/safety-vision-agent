# API 契约

真实地址和密钥由 `.env` 配置，本仓库不提交真实值。外部 VLM/YOLO API 必须返回严格 JSON；后端会使用 Pydantic schema 校验返回体。

## 通用约定

- 鉴权：如果配置了 `*_API_KEY`，Agent 会发送 `Authorization: Bearer <token>`。
- 坐标：所有 `bbox` 均为像素坐标 `[x1, y1, x2, y2]`，原点在图片左上角。
- 置信度：`confidence` 使用 `0.0 - 1.0` 浮点数。
- MVP 数据库：仅 SQLite，路径由 `SQLITE_PATH` 配置。
- Agent 编排：LangGraph。
- 主交互：前端优先使用 `POST /api/chat`，旧 task polling 不再是主流程。

## 后端 Agent API

### 上传图片

```text
POST /api/files/images
Content-Type: multipart/form-data
```

响应：

```json
{
  "file_id": "file_xxx",
  "filename": "site.jpg",
  "path": "/abs/runtime/uploads/file_xxx.jpg"
}
```

### 多轮 Agent 对话

```text
POST /api/chat
```

请求：

```json
{
  "conversation_id": null,
  "file_id": "file_xxx",
  "image_path": null,
  "message": "分析这张图有没有隐患",
  "selected_bbox": null
}
```

响应：

```json
{
  "conversation_id": "conv_xxx",
  "answer": "发现 1 处明确隐患...",
  "latest_analysis_id": "analysis_xxx",
  "fused_result": {
    "hazards": [],
    "detections": [],
    "uncertain_items": [],
    "uncertain_followups": [],
    "summary": "未形成明确隐患结论。",
    "recommendations": []
  },
  "tool_calls": [
    {
      "tool": "vlm_hazard_analysis_tool",
      "status": "ok",
      "input": {},
      "output": {},
      "latency_ms": 12.3
    }
  ],
  "artifacts": {},
  "errors": []
}
```

同一 `conversation_id` 下的追问可以不带 `file_id`，例如“刚才第 2 个隐患依据是什么？”会优先读取 SQLite 中的最新融合结果，不重新调用 VLM/YOLO。

### 兼容分析接口

```text
POST /api/analysis
GET /api/analysis/{analysis_id}
GET /api/analysis/tasks/{task_id}
```

这些接口仅保留兼容能力，内部仍走 inline Agent，不再导入 Celery、Redis 或队列任务。

### 人工复核

```text
POST /api/reviews
```

### 整改任务

```text
POST /api/remediations
POST /api/remediations/{task_id}/evidence
POST /api/remediations/{task_id}/verify
```

### 标注反哺

```text
POST /api/annotations/from-analysis
GET /api/annotations/samples/{sample_id}
PATCH /api/annotations/samples/{sample_id}/review
POST /api/annotations/samples/{sample_id}/commit
```

## 微调 VLM API

### 请求

```json
{
  "image_path": "uploads/example.jpg",
  "question": "识别图中的四口五临边安全隐患。",
  "candidate_rules": [],
  "target_bbox": null,
  "context": {
    "scene": "four_openings_edges"
  }
}
```

### 响应

```json
{
  "objects": [
    {
      "object_id": "floor_edge_protection",
      "object_name": "楼层临边防护",
      "bbox": [120, 80, 780, 620],
      "status": "confirmed_hazard",
      "hazard_type_id": "missing_protection",
      "hazard_type": "防护缺失",
      "visual_evidence": "图中楼层临边未见连续防护栏杆。",
      "missing_evidence": null,
      "evidence_sufficiency": "sufficient",
      "uncertainty_reason": null,
      "rule": "楼层临边应设置防护栏杆或其他防坠落措施。",
      "confidence": 0.82
    }
  ],
  "summary": "发现 1 处楼层临边防护缺失隐患。"
}
```

`status` 允许值：`confirmed_hazard`、`safe`、`uncertain`。

## YOLO 检测 API

### 请求

```json
{
  "image_path": "uploads/example.jpg",
  "tasks": ["person", "helmet", "no_helmet"],
  "confidence_threshold": 0.25
}
```

### 响应

```json
{
  "detections": [
    {
      "label": "no_helmet",
      "bbox": [300, 120, 420, 500],
      "confidence": 0.91
    }
  ],
  "summary": {
    "person_count": 3,
    "helmet_count": 2,
    "no_helmet_count": 1
  }
}
```

`label` 允许值：`person`、`helmet`、`no_helmet`。

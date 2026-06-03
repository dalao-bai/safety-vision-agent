# API 契约草案

真实地址和密钥由 `.env` 配置，本仓库不提交真实值。

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

## 后端接口

### 上传图片

```text
POST /api/files/images
```

### 创建分析任务

```text
POST /api/analysis
```

### 查询任务状态

```text
GET /api/analysis/tasks/{task_id}
```

### 查询分析结果

```text
GET /api/analysis/{analysis_id}
```

### 人工复核

```text
POST /api/reviews
```

请求：

```json
{
  "analysis_id": "analysis_xxx",
  "item_type": "hazard",
  "item_index": 0,
  "decision": "accept",
  "reviewer": "human",
  "revised_json": {},
  "note": "确认该隐患判断。"
}
```

### 创建整改任务

```text
POST /api/remediations
```

请求：

```json
{
  "conversation_id": "conv_xxx",
  "analysis_id": "analysis_xxx",
  "hazard_index": 0,
  "title": "整改任务 1：楼层临边防护",
  "recommendation": "请设置连续可靠的防护栏杆。",
  "responsible_person": null,
  "due_at": null,
  "hazard_json": {}
}
```

### 上传整改证据

```text
POST /api/remediations/{task_id}/evidence
```

### 复核整改结果

```text
POST /api/remediations/{task_id}/verify
```

### 生成报告

```text
POST /api/reports
```

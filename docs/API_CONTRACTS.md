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

## YOLO 检测 API

Agent 只接受 YOLO API，不在本项目中保存或加载 YOLO 权重。

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

### 创建整改任务

```text
POST /api/remediations
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

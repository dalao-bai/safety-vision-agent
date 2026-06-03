# API 契约草案

## 微调 VLM API

真实地址和密钥由 `.env` 配置，本仓库不提交真实值。

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

### 多轮对话

```text
POST /api/chat
```

### 查询会话

```text
GET /api/conversations/{conversation_id}
```

### 生成报告

```text
POST /api/reports
```

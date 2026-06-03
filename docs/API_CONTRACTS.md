# API 契约草案

真实地址和密钥由 `.env` 配置，本仓库不提交真实值。外部 API 必须返回严格 JSON；后端会使用 Pydantic schema 校验返回体。

## 通用约定

- 鉴权：如果配置了 `*_API_KEY`，Agent 会发送 `Authorization: Bearer <token>`。
- 坐标：所有 `bbox` 均为像素坐标 `[x1, y1, x2, y2]`，原点在图片左上角，要求 `x1 < x2` 且 `y1 < y2`。
- 置信度：`confidence` 使用 `0.0 - 1.0` 浮点数。
- 成功响应：HTTP `2xx` + JSON body。
- 失败响应：HTTP `4xx/5xx` + JSON body，推荐格式如下：

```json
{
  "error": {
    "code": "invalid_image",
    "message": "图片无法读取或格式不受支持。"
  }
}
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

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `image_path` | string | 是 | Agent 后端保存的图片路径，具体可由模型服务按部署方式读取或映射。 |
| `question` | string | 是 | 本轮用户问题或 Agent 构造的分析指令。 |
| `candidate_rules` | array[object] | 是 | 候选四口五临边规则块。 |
| `target_bbox` | array[number] 或 null | 否 | 用户指定局部区域；为空表示分析整图。 |
| `context.scene` | string | 是 | 固定为 `four_openings_edges`。 |

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

### VLM 允许值

`object_id` 只能取：

```text
stair_opening_protection
elevator_shaft_protection
reserved_opening_protection
passage_entrance_protection
balcony_edge_protection
roof_edge_protection
floor_edge_protection
foundation_pit_edge_protection
ramp_edge_protection
```

`status` 只能取：

```text
confirmed_hazard
safe
uncertain
```

`hazard_type_id` 在 `status = confirmed_hazard` 时填写，只能取：

```text
missing_protection
discontinuous_protection
temporary_substitute
unfixed_or_weak_protection
opening_uncovered
cover_unfixed_or_insufficient
door_open_or_missing
canopy_missing_or_invalid
```

`uncertainty_reason` 在 `status = uncertain` 时填写，只能取：

```text
protective_component_not_visible
visual_rule_evidence_insufficient
external_context_required
```

`evidence_sufficiency` 只能取：

```text
sufficient
insufficient
```

字段一致性要求：

- `confirmed_hazard`：`hazard_type_id`、`hazard_type`、`visual_evidence`、`rule` 必须有值；`missing_evidence` 和 `uncertainty_reason` 应为 `null`。
- `safe`：`hazard_type_id`、`hazard_type`、`missing_evidence`、`uncertainty_reason` 应为 `null`。
- `uncertain`：`hazard_type_id`、`hazard_type` 应为 `null`；`missing_evidence`、`uncertainty_reason` 必须有值；`evidence_sufficiency` 应为 `insufficient`。

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

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `image_path` | string | 是 | Agent 后端保存的图片路径，具体可由 YOLO 服务按部署方式读取或映射。 |
| `tasks` | array[string] | 是 | 当前固定请求 `person`、`helmet`、`no_helmet`。 |
| `confidence_threshold` | number | 是 | 检测置信度阈值。 |

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

### YOLO 允许值

`label` 只能取：

```text
person
helmet
no_helmet
```

`summary` 至少包含：

```text
person_count
helmet_count
no_helmet_count
```

如果没有检测结果，返回：

```json
{
  "detections": [],
  "summary": {
    "person_count": 0,
    "helmet_count": 0,
    "no_helmet_count": 0
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

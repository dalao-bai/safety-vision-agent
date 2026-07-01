# 数据格式参考

开发时查阅。各步骤的 JSON 结构、字段取值、磁盘文件格式。

流程图见 [flow_diagrams.md](flow_diagrams.md)

---

## 1. VLM 返回的原始 JSON

VLM 被要求只输出 JSON，`_VLM_INSTRUCTION_SIMPLE` 模式下格式如下：

```json
{
  "scene": "四口五临边",
  "hazards": [
    {
      "related_object": "楼梯口防护",
      "hazard_type_id": "missing_protection",
      "status": "confirmed_hazard",
      "visual_evidence": "楼梯洞口及梯段临边未见防护栏杆",
      "object_bbox": [120, 80, 400, 350]
    },
    {
      "related_object": "基坑临边防护",
      "hazard_type_id": null,
      "status": "uncertain",
      "visual_evidence": "基坑边缘区域被遮挡，无法判断是否有防护",
      "object_bbox": [50, 200, 300, 480]
    }
  ]
}
```

**`hazard_type_id` 取值：**

| 值 | 含义 |
|---|---|
| `missing_protection` | 缺少防护 |
| `discontinuous_protection` | 防护不连续 |
| `temporary_substitute` | 临时替代措施 |
| `unfixed_or_weak_protection` | 固定不牢或防护薄弱 |
| `door_open_or_missing` | 防护门缺失或敞开 |
| `access_or_obstruction_issue` | 通道异常或通行障碍 |
| `null` | 无法判断 |

**`status` 取值：**

| 值 | 含义 |
|---|---|
| `confirmed_hazard` | 明确有隐患 |
| `uncertain` | 证据不足，无法判断 |
| `safe` | 未见明显隐患 |

**兼容格式：** `_extract_hazards` 还能处理以下变体：
- 顶层是数组（无 `scene` 包装）
- `hazards` 键名替换为 `objects` 或 `results`
- 单个对象（不是数组）

---

## 2. 上传图片接口返回（前端收到的）

`POST /sessions/{sid}/images` 成功时返回：

```json
{
  "image_id": 1,
  "scene": "四口五临边",
  "hazards": [
    {
      "object_id": "stair_opening_protection",
      "object_name": "楼梯口防护",
      "status": "confirmed_hazard",
      "hazard_type_id": "missing_protection",
      "bbox": [120, 80, 400, 350],
      "visual_evidence": "楼梯洞口及梯段临边未见防护栏杆"
    }
  ],
  "assistant_message": "已识别图片，发现 1 处明确隐患..."
}
```

注意：`object_id` 是由 VLM 输出的 `related_object`（中文名）通过 KGStore 映射得来的。

**批量上传** `POST /sessions/{sid}/images/batch` 返回：

```json
{
  "total": 3,
  "succeeded": 2,
  "failed": 1,
  "summary": {
    "confirmed_hazard": 3,
    "uncertain": 1,
    "safe": 0
  },
  "failed_files": [
    {"filename": "bad.gif", "reason": "unsupported_type"}
  ],
  "assistant_message": "已完成 2 张图识别...",
  "batch_id": "uuid-string"
}
```

**失败原因取值：** `unsupported_type` / `file_too_large` / `invalid_path` / `vlm_error`

---

## 3. hazards 表字段值

一条 `Hazard` 记录在数据库里的实际存储：

| 字段 | 类型 | 示例值 | 说明 |
|---|---|---|---|
| `id` | INTEGER | `1` | 自增主键 |
| `image_id` | INTEGER | `1` | 关联图片 |
| `object_id` | TEXT | `staircase_opening_protection` | 防护对象 id |
| `status` | TEXT | `confirmed_hazard` | VLM 判定状态 |
| `hazard_type_id` | TEXT/NULL | `missing_protection` | 隐患类型，可为 NULL |
| `bbox` | TEXT | `[120, 80, 400, 350]` | JSON 字符串，读取时反序列化 |
| `reasoning_chain` | TEXT | `[{"step":1,...}]` | JSON 字符串，可为空数组 |
| `visual_evidence` | TEXT | `楼梯洞口未见防护栏杆` | 视觉证据描述 |
| `rule_basis` | TEXT | `JGJ 80-2016 第4.1.3条` | 标准条文依据 |
| `evidence_sufficiency` | TEXT | `sufficient` | 证据充分性 |
| `uncertainty_reason` | TEXT/NULL | `区域被遮挡` | uncertain 时填写 |
| `missing_evidence` | TEXT/NULL | `需要近景照片` | 缺少的证据描述 |
| `confirmed` | INTEGER | `0` / `1` | 用户是否确认，0=未确认 |

---

## 4. images 表状态机

```
awaiting_confirmation   ← 上传识别后的初始状态
        │
   ┌────┴────┐
   │         │
confirmed   corrected_submitted
```

| 状态 | 触发条件 | 影响 |
|---|---|---|
| `awaiting_confirmation` | 图片上传成功后 | 默认状态 |
| `confirmed` | 用户调用 `confirm_hazards` | hazards 纳入报告 |
| `corrected_submitted` | 用户调用 `submit_correction` | 样本进入微调流水线 |

---

## 5. 纠错飞轮写入的文件

`submit_correction` 触发后，`correction/intake.py` 在 `runtime/pipeline_intake/` 下写入：

**`images/{stem}.json`** — pipeline 格式，供微调流水线消费：

```json
{
  "sample_id": "20260630T070056_074636de_ef1bf401_a1b2c3d4",
  "image_path": "runtime/pipeline_intake/images/xxx.png",
  "scene": "四口五临边",
  "objects": [
    {
      "object_id": "stair_opening_protection",
      "object_name": "楼梯口防护",
      "status": "confirmed_hazard",
      "hazard_type_id": "missing_protection",
      "hazard_type": null,
      "bbox": [120, 80, 400, 350],
      "visual_evidence": "楼梯洞口未见防护栏杆",
      "evidence_sufficiency": "sufficient",
      "uncertainty_reason": null,
      "missing_evidence": null
    }
  ],
  "agent_source": "agent_qa",
  "agent_correction_note": "用户说明的错误内容"
}
```

**`corrections/{stem}.correction.json`** — 完整快照，含推理链：

```json
{
  "source": "agent_qa",
  "created_at": "2026-06-30T07:01:47Z",
  "note": "用户说明的错误内容",
  "original_vlm": {
    "scene": "四口五临边",
    "hazards": [
      {
        "...": "同 pipeline 格式",
        "rule_basis": "JGJ 80-2016 第4.1.3条",
        "reasoning_chain": [{"step": 1, "...": "..."}]
      }
    ]
  }
}
```

`stem` 格式：`{原始文件名}_{uuid[:8]}`，UUID 后缀防止重复文件名。

---

## 6. Agent 消息端点返回

`POST /sessions/{sid}/messages` 返回：

```json
{
  "reply": "根据JGJ 80-2016第4.1.3条，楼梯洞口应设置防护栏杆，高度不低于1.2m..."
}
```

---

## 7. query_statistics 返回

```json
{
  "total": 15,
  "date_from": "2026-06-01",
  "date_to": "2026-06-30",
  "confirmed_only": true,
  "breakdown": [
    {"hazard_type_id": "missing_protection", "object_id": "stair_opening_protection", "count": 6},
    {"hazard_type_id": "discontinuous_protection", "object_id": "foundation_pit_edge_protection", "count": 4}
  ]
}
```

---

## 8. 防护对象 object_id 对照表

| object_id | 中文名 |
|---|---|
| `stair_opening_protection` | 楼梯口防护 |
| `elevator_shaft_protection` | 电梯井口防护 |
| `reserved_opening_protection` | 预留洞口防护 |
| `passage_entrance_protection` | 通道口防护 |
| `balcony_edge_protection` | 阳台临边防护 |
| `roof_edge_protection` | 屋面临边防护 |
| `floor_edge_protection` | 楼层临边防护 |
| `foundation_pit_edge_protection` | 基坑临边防护 |
| `ramp_edge_protection` | 跑道（斜道）临边防护 |

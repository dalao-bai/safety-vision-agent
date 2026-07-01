# Agent 功能流程图

> 数据格式（JSON 结构、字段值）见 [data_reference.md](data_reference.md)

---

## 功能一：图片上传 + VLM 识别

```
前端 POST /sessions/{sid}/images
        │
        ▼
  images.py: upload_image()
        │
        ├─ session 不存在 → 404
        ├─ 格式不在 {png/jpg/jpeg/webp/bmp} → 400
        ├─ 文件大小 > 10MB → 413
        ├─ 存磁盘 runtime/uploads/{sid}_{sha1[:16]}{suffix}
        │
        ▼
  detector.detect(path)          ← vlm/detector.py
        │
        ├─ 图片转 base64 data URL
        ├─ 拼 VLM prompt（含 9 个防护对象名称约束）
        ├─ 调 vLLM API（temperature=0）
        ├─ 解析 JSON → DetectionResult
        │
        ├─ JSON 解析失败 → DetectionError → 422 识别失败
        └─ VLM 输出格式无法识别 → DetectionError → 422 识别失败
                │
                ▼（识别成功）
  orchestrator.ingest_image()
        │
        ├─ DB: images 表写一行（status=awaiting_confirmation）
        ├─ DB: hazards 表写 N 行（confirmed=0）
        └─ DB: messages 表写 assistant 消息（识别摘要）
                │
                ▼
        返回 image_id + hazards 给前端
        （注：识别失败时不写 DB，图片记录不会产生）
```

---

## 功能二：用户发消息 → Agent 循环

```
前端 POST /sessions/{sid}/messages {"text": "..."}
        │
        ▼
  messages.py: post_message()
        │
        ├─ session 不存在 → 404
        ▼
  Orchestrator.handle_message()
        │
        ├─ DB 写 user 消息
        ├─ 构建历史上下文（_build_messages，已处理的图压缩）
        │
        └─ while 循环 ──────────────────────────────────────────────────────────┐
                │                                                               │
          超时检测 (> 30s) ──→ outcome=timeout                                  │
          迭代检测 (≥ 5次) ──→ outcome=max_iter ← 这两种异常终态都走下面的"终止路径"  │
                │                                                               │
                ▼                                                               │
          调 LLM（带 TOOL_SCHEMAS）                                              │
                │                                                               │
          ┌─────┴──────────┐                                                    │
          │ 有 tool_calls   │ 无 tool_calls                                      │
          │                │                                                    │
          ▼                ▼                                                    │
    ToolGuard 校验    outcome=no_tool_calls                                     │
          │                │                                                    │
    ┌─────┴──────────┐      └─────────────────────────────────────────── 终止 ──┘
    │ 校验失败         │ 校验通过
    │                 │
    │  unknown_tool   ▼
    │  missing_params dispatch_tool()
    │  duplicate_call         │
    │  ↓ 错误信息回传 LLM     ┌─────┴──────────────────┐
    │  ↓ LLM 重试调用         │                        │
    └──────────────── 继续循环                    其他工具
                                               (结果回传 LLM → 继续循环)
                                    │
                                    ▼（终止路径，任意 outcome 都走这里）
                              DB 写 assistant 消息
                              flush_tool_traces（批量回填 loop_outcome）
                              返回 {reply: "..."} 给前端
```

**loop_outcome 终态含义：**

| outcome | 触发条件 | 用户体验 |
|---|---|---|
| `no_tool_calls` | LLM 直接输出文字，未调工具 | 正常回复 |
| `timeout` | 循环超 30s | 可能回复不完整 |
| `max_iter` | 连续调用工具超 5 次 | LLM 被强制截断 |

---

## 功能三：查询知识图谱 / 标准条文

```
用户: "楼梯洞口应该怎么防护？"
        │
        ▼
  LLM 决定调 search_standards
        │
        ├─── 跨轮缓存命中？（同参数本 session 内已调过）
        │         └─ 是 → 直接返回缓存结果，不重复查
        │
        └─── search_standards(query)
                  │
                  ▼
             retrieval/standards.py
                  │
                  ├─ Dense 向量检索（ChromaDB, top-20）
                  │       └─ ChromaDB 不可用（未建索引 / 进程异常）
                  │               → 降级：跳过 Dense，只用 BM25
                  │
                  ├─ BM25 检索（top-20）
                  │       └─ BM25 也不可用 → 返回空列表，告知用户检索失败
                  │
                  ├─ RRF 融合（k=60）
                  ├─ CrossEncoder 重排（top-5）
                  │       └─ 重排模型未加载（HF_HUB_OFFLINE=1 且模型未缓存）
                  │               → 跳过重排，直接返回 RRF top-5
                  │
                  └─ 返回原文片段 + 出处，写入跨轮缓存
```

**跨轮缓存说明：** `search_standards` 和 `query_statistics` 是只读工具，同一 session 内相同参数重复调用时命中缓存，不再访问 ChromaDB。缓存存于 `Orchestrator._session_cross_caches`，进程重启后清空。

---

## 功能四：确认隐患

```
用户: "确认这张图" / "全部确认"
        │
        ▼
  LLM 调 confirm_hazards(image_id)
  或    confirm_hazards_batch(confirm_all=true)
        │
        ▼
  dispatch_tool()
        │
        ├─ _owns_image() 校验图片归属
        │     └─ 图片不属于本 session → 返回 {ok: false, error: ...}
        ├─ DB: hazards.confirmed = 1（UPDATE）
        ├─ DB: images.status = "confirmed"（UPDATE）
        └─ 外部校验：读 DB 验证 status 确实变了
              └─ 未变 → 返回 warning，LLM 可重试
                │
                ▼
        返回 {ok: true, image_id: N}
```

---

## 功能五：提交纠错

```
用户: "这张图识别错了，基坑边有护栏"
        │
        ▼
  LLM 调 submit_correction(image_id, note)
        │
        ▼
  dispatch_tool()
        │
        ├─ _owns_image() 校验
        │     └─ 不属于本 session → {ok: false}
        ├─ 图片无 hazards 记录 → {ok: false, error: "no hazards stored"}
        ├─ 从 DB 重建 DetectionResult
        │
        ▼
  correction/intake.py: deposit()
        │
        ├─ 复制图片到 runtime/pipeline_intake/images/{stem}{suffix}
        ├─ 写 runtime/pipeline_intake/images/{stem}.json
        │     （pipeline 格式，供微调流水线消费）
        └─ 写 runtime/pipeline_intake/corrections/{stem}.correction.json
              （完整快照，含 rule_basis / reasoning_chain）
        │
        ├─ DB: corrections 表写一行
        ├─ DB: images.status = "corrected_submitted"
        └─ 返回 {ok: true, intake_path: "runtime/pipeline_intake"}
```

---

## 功能六：导出报告

```
用户: "导出报告"
        │
        ▼
  LLM 调 export_report()
        │
        ▼
  dispatch_tool()
        │
        ├─ DB: get_confirmed_hazards(session_id)
        │       └─ 只取 confirmed=1 的隐患
        │       └─ 无已确认隐患 → 报告写"未发现已确认隐患"，仍生成文件
        │
        ▼
  reports/builder.py: build_docx_report()
        │
        ├─ 遍历隐患，从 KG 补全 object_name / hazard_name
        ├─ rule_basis 为空时显示"暂无"（不做 KG 补全）
        └─ 生成 runtime/reports/session_{sid}_report.docx
                │
                ▼
  LLM 返回下载路径给用户
  用户请求下载: GET /sessions/{sid}/report/download
        │
        ├─ session 不存在 → 404
        ├─ 文件不存在（未调 export_report）→ 404 "report not generated"
        └─ 存在 → 返回 .docx 文件流
```

---

## 功能七：统计查询

```
用户: "上周发现了多少隐患？哪类最多？"
        │
        ▼
  LLM 调 query_statistics(date_from, date_to, hazard_type_id, object_id, confirmed_only)
        │
        ▼
  db.query_hazard_stats()
        │
        ├─ 动态拼 WHERE 子句（所有参数可选）
        ├─ confirmed_only=true（默认）→ 额外加 status='confirmed_hazard'
        ├─ 跨所有 session 统计（不限于当前会话）
        └─ 返回: {total, breakdown: [{hazard_type_id, object_id, count}×top-10]}
```

---

## 附：ImageRecord 状态机

```
                  上传图片
                     │
                     ▼
          awaiting_confirmation
                     │
          ┌──────────┴──────────┐
          │                     │
   confirm_hazards        submit_correction
          │                     │
          ▼                     ▼
      confirmed         corrected_submitted
```

两个终态都不可逆，对应的隐患处理方式不同：
- `confirmed` → 纳入报告
- `corrected_submitted` → 纳入微调流水线，不进报告

---

## 附：Agent 工具决策参考

| 用户说了什么 | LLM 通常调的工具 |
|---|---|
| 这张图发现了什么 / 有什么隐患 | `get_session_hazards(image_id=N)` |
| 全部隐患摘要 / 本次巡检结果 | `get_session_hazards()` |
| 楼梯洞口怎么防护 / 某对象定义 | `search_standards(query=...)` |
| 标准原文 / JGJ 条文 | `search_standards(query=...)` |
| 确认这张图 / 结果没问题 | `confirm_hazards(image_id=N)` |
| 全部确认 / 都没问题 | `confirm_hazards_batch(confirm_all=true)` |
| 识别错了 / 这里其实有护栏 | `submit_correction(image_id=N, note=...)` |
| 导出报告 / 生成报告 | `export_report()` |
| 上周多少隐患 / 哪类最多 | `query_statistics(date_from=..., date_to=...)` |

# 批量上传方案设计

## 1. 问题诊断

### 1.1 现有架构的单张上传流程

```
POST /sessions/{id}/images（每张）
  → VLM 识别（同步阻塞）
  → db.add_image + db.add_hazards
  → db.add_message(assistant, "已完成识别，共 N 处：... 是否正确？")
  → db.add_message(system,    "[context] 待确认图片 image_id=X")
  → 返回
```

每张图产生 2 条消息，每次对话 `_build_messages` 全量加载历史。

---

### 1.2 批量上传时的连锁问题

#### 问题 A：上下文爆炸

30 张图产生 60 条历史消息，在用户开口问第一个问题之前 context 已经塞满：

| 来源 | 每张估算 token | 30 张合计 |
|---|---|---|
| assistant 识别摘要（含 visual_evidence、rule_basis） | ~300 token | ~9 000 token |
| system image_id context | ~15 token | ~450 token |
| system prompt 本身 | ~250 token | 250 token（固定） |
| **问答开始前合计** | — | **~9 700 token** |

GPT-4o / 本地模型的有效上下文大幅被识别摘要占用，后续问答轮的空间不足，且每轮调用费用随历史长度线性增长。

#### 问题 B：确认流程错乱

System prompt 要求 Agent 对每张图问「是否正确」，30 张图导致 30 个悬挂的未答确认问题堆在历史里。用户回「都对」时 Agent 无法明确对应哪张图。

#### 问题 C：VLM 串行阻塞

单张接口串行调 VLM，30 张需等待 30 × T_vlm 时间（T_vlm 通常 2-10 秒），用户体验不可接受。

#### 问题 D：部分失败无法处理

串行流程中第 15 张识别失败会中断整个批次，已处理的 14 张结果无法返回给用户。

#### 问题 E：工具循环上限被穿透

批量确认时 Agent 需要对每张图调一次 `confirm_hazards`，30 张 = 30 次工具调用，远超 `MAX_TOOL_ITERATIONS`（默认 5）。

---

## 2. 解决方案

### 2.1 核心设计原则

1. **识别与确认彻底解耦**：识别结果全部进 DB，上下文只放聚合摘要，不放逐张详情。
2. **批量确认是一次工具调用**：新增 `confirm_hazards_batch` 工具，一次确认多张。
3. **VLM 并发识别**：用线程池并行处理，部分失败不影响其余结果。
4. **上下文常数化**：无论上传多少张，批量上传只往对话历史写固定条数消息。

---

### 2.2 新增接口

```
POST /sessions/{id}/images/batch
  multipart: files[]（多文件）
```

返回：

```json
{
  "batch_id": "550e8400-e29b-41d4-a716-446655440000",
  "total": 30,
  "succeeded": 28,
  "failed": 2,
  "summary": {
    "confirmed_hazard": 32,
    "uncertain": 10,
    "safe": 6
  },
  "failed_files": [
    {"filename": "img_15.jpg", "reason": "vlm_error"},
    {"filename": "img_22.jpg", "reason": "file_too_large"}
  ],
  "assistant_message": "已完成 28 张图识别，..."
}
```

**`batch_id` 说明：** 使用 `uuid4()` 在请求时生成，**不持久化到 DB**，仅供调用方做日志关联。没有任何后续 API 通过 `batch_id` 查询，不建表。

---

### 2.3 批量识别流程

```
POST /sessions/{id}/images/batch
  ↓
1. 逐文件校验（类型/大小）
   → 无效文件记入 failed_files（附 reason），跳过继续
   → 若全部文件无效，返回 HTTP 422，流程终止
  ↓
2. 有效文件落盘（生成本地路径）
  ↓
3. ThreadPoolExecutor 并发调 VLM（max_workers 从配置读取，默认 4）
   成功：db.add_image + db.add_hazards
   失败：记录 error，不写 DB，不中断其余
  ↓
4. 汇总结果
  ↓
5a. succeeded > 0：
    db.add_message(session_id, "assistant", 聚合摘要)
    db.add_message(session_id, "system",    "[context] 批量上传 image_ids=3,4,5,…")
5b. succeeded == 0：
    db.add_message(session_id, "assistant", 全部失败提示)
    （不写 system context，无 image_id 可引用）
  ↓
6. 返回 HTTP 200
```

**校验失败粒度**：跳过无效文件，继续处理有效文件，与 VLM 运行时失败的处理一致。只有全部文件均无效时才提前返回 422。

**DB 写入时机**：所有 VLM 并发任务结束后，统一写消息到 DB，再返回响应，避免客户端收到响应后立即发消息而 DB 尚未落地。

**磁盘孤立文件**：VLM 失败的图片已落盘但无 DB 记录，与单张上传的处理保持一致（均留在磁盘），不在本次范围内清理。

#### 并发控制

```python
MAX_VLM_WORKERS = int(os.getenv("MAX_VLM_WORKERS", 4))
```

vLLM 本地部署需根据 GPU 显存和 batch size 限制工作线程数，避免 OOM。

---

### 2.4 上下文压缩：只写两条消息（succeeded > 0 时）

#### assistant 聚合摘要

```
已完成 28 张图识别（2 张失败：img_15.jpg、img_22.jpg），共发现：

| 状态 | 数量 |
|---|---|
| 明确隐患 | 32 处 |
| 证据不足 | 10 处 |
| 未见明显隐患 | 6 处 |

隐患最多的类型：防护缺失 18 处、防护不连续 8 处。
涉及对象：基坑临边 15 处、楼梯口 12 处、预留洞口 5 处。

如需查看某张图的详细结果，告诉我图片序号或 image_id；
输入「全部确认」批量标记已确认，或指定「确认第 1、3、5 张」。
```

token 估算约 150 token，与张数无关。

#### system context（一条）

```
[context] 批量上传 image_ids=3,4,5,6,7,8,…,30
```

格式固定为 `[context] 批量上传 image_ids=` 前缀 + 逗号分隔的 image_id 整数列表。`_build_messages` 通过此前缀识别批量上传条目（见 2.7）。

对话历史新增 **2 条消息**，与张数无关。

#### 全部失败时的 assistant 消息

```
批量上传失败：全部 30 张图 VLM 识别出错，未生成任何隐患记录。请检查模型服务或重新上传。
```

此时不写 system context。返回 HTTP 200，`succeeded=0`（请求格式合法，失败属运行时错误，不应是 4xx）。

---

### 2.5 工具层扩展

#### 新增：`confirm_hazards_batch`

```json
{
  "name": "confirm_hazards_batch",
  "description": "批量确认多张图片的识别结果。image_ids 传具体列表，或 confirm_all=true 确认本会话全部待确认图片。",
  "parameters": {
    "image_ids": {"type": "array", "items": {"type": "integer"}},
    "confirm_all": {"type": "boolean"}
  }
}
```

dispatch 实现：

```python
if name == "confirm_hazards_batch":
    if args.get("confirm_all"):
        ids = ctx.db.get_pending_image_ids(ctx.session_id)
    else:
        ids = [int(i) for i in args.get("image_ids", [])]
    ids = [i for i in ids if _owns_image(ctx, i)]  # 鉴权过滤
    for img_id in ids:
        ctx.db.mark_hazards_confirmed(img_id)
        ctx.db.set_image_status(img_id, "confirmed")
    return {"ok": True, "confirmed_count": len(ids), "image_ids": ids}
```

一次工具调用解决所有确认，不受 `MAX_TOOL_ITERATIONS` 限制。

#### 新增 DB 方法：`get_pending_image_ids`

```python
def get_pending_image_ids(self, session_id: int) -> list[int]:
    with self._lock:
        rows = self._conn.execute(
            "SELECT id FROM images WHERE session_id=? AND status='awaiting_confirmation'",
            (session_id,)
        ).fetchall()
    return [r[0] for r in rows]
```

语义边界：只返回本会话内 `status='awaiting_confirmation'` 的图片，不越权访问其他会话。

#### 修改：`get_session_hazards` 增加过滤参数

```json
{
  "status_filter": {
    "type": "string",
    "description": "可选：uncertain / confirmed_hazard / safe，只返回该状态的隐患"
  }
}
```

支持「先看证据不足的」「只看明确隐患」等自然语言指令。

---

### 2.6 System Prompt 补充规则

```
6. 批量上传场景：
   - 识别完成后的聚合摘要已包含统计信息，无需再逐张复述。
   - 用户说「全部确认」→ 调用 confirm_hazards_batch(confirm_all=true)。
   - 用户指定部分确认 → 调用 confirm_hazards_batch(image_ids=[...])。
   - 用户要看某张详情 → 调用 get_session_hazards(image_id=X)。
   - 用户要看证据不足的 → 调用 get_session_hazards(status_filter="uncertain")。
```

---

### 2.7 `_build_messages` 批量上传压缩

`_build_messages` 新增对 `_BATCH_CTX_PREFIX` 的识别分支，与单张上传的 `_CTX_PREFIX` 并列：

```python
_CTX_PREFIX       = "[context] 待确认图片 image_id="
_BATCH_CTX_PREFIX = "[context] 批量上传 image_ids="
```

**第一遍扫描（识别终态）：**

遇到 `_BATCH_CTX_PREFIX` 系统消息时，解析出 image_ids 列表，检查是否**全部**处于终态（`confirmed` 或 `corrected_submitted`）。若是，将对应的前一条 assistant 聚合消息加入待压缩集合。

**第二遍构建（输出压缩后消息）：**

- 批量 assistant 消息处于待压缩集合 → 替换为一行占位：
  ```
  [批量已处理] 共N张，明确隐患M处，全部已确认/已纠错。
  ```
- 批量 system context 消息 → 若已全部终态，替换为：
  ```
  [已处理] 批量上传 共N张，全部已处理
  ```

原始消息仍完整存 DB，只是发给模型时压缩。

**单张上传的既有压缩逻辑不变**，两条路径并行不干扰。

---

### 2.8 长会话上下文管理（单张补充）

单张上传场景下，`_build_messages` 已实现：一张图的 `image_id` 对应隐患状态一旦变为 `confirmed` 或 `corrected_submitted`，将该图 assistant 摘要消息替换为一行占位：

```
[已处理] image_id=5：基坑临边防护/防护缺失，已确认。
```

此逻辑不受批量改动影响，继续生效。

---

## 3. 改动清单

| 文件 | 改动 |
|---|---|
| `app/api/images.py` | 新增 `POST /sessions/{id}/images/batch` 路由 |
| `app/agent/orchestrator.py` | 新增 `handle_batch_images`；`_build_messages` 新增 `_BATCH_CTX_PREFIX` 分支 |
| `app/agent/tools.py` | 新增 `confirm_hazards_batch`；`get_session_hazards` 增加 `status_filter` |
| `app/agent/prompts.py` | 追加批量场景规则 6 |
| `app/persistence/db.py` | 新增 `get_pending_image_ids(session_id)` |
| `app/config.py` | 新增 `MAX_VLM_WORKERS` 配置项 |
| `backend/requirements.txt` | 无新依赖（`concurrent.futures` 标准库；`uuid` 标准库） |
| `tests/test_api.py` | 批量上传集成测试（正常批、部分失败、全部失败、全部无效文件） |
| `tests/test_orchestrator.py` | `handle_batch_images` 单元测试；`_build_messages` 批量压缩测试 |
| `tests/test_tools.py` | `confirm_hazards_batch` 测试（image_ids 指定、confirm_all、鉴权过滤） |
| `tests/test_db.py` | `get_pending_image_ids` 测试 |

---

## 4. 不在本次范围

- 前端进度条（批量上传期间的实时进度推送，需 WebSocket 或 SSE）
- 跨会话的长期对话记忆
- 图片去重（相同 sha1 的图在同一会话重复上传）
- 孤立磁盘文件定期清理（VLM 失败留盘的文件）

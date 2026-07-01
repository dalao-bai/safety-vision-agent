# 上下文管理与记忆管理

> 代码位置：`backend/app/agent/orchestrator.py`

---

## 概览

Agent 的"记忆"完全存在 SQLite 里，没有向量记忆或外部存储。每次用户发消息时，`_build_messages` 从数据库重建完整上下文，再发给 LLM。上下文管理分两层：**跨轮压缩**（减少已处理图片的 token 占用）和**单轮截断**（防止历史消息超出模型上下文窗口）。

```
SQLite messages 表（全量持久化）
        │
        ▼
_build_messages()   ← 每次 handle_message 调用时重建
        │
        ├── 跨轮压缩：已确认/已纠错图片的识别摘要替换为一行占位
        ├── system 上下文合并到首条 system 消息（OpenAI 兼容要求）
        └── _trim_convo()：超出字符上限时从头截断（保底保留 8 条）
        │
        ▼
发给 LLM（当次内存，不写回数据库）
```

---

## 1. 持久化层：SQLite messages 表

所有消息都写入 `messages` 表，字段：`session_id / role / content / created_at`。

**role 取值：**

| role | 写入时机 | 内容 |
|---|---|---|
| `user` | 用户发消息 | 用户原文 |
| `assistant` | LLM 回复 / 识别完成 | 回复文字 或 识别摘要 |
| `system` | 上传图片后 | `[context] 待确认图片 image_id=N` 或 `[context] 批量上传 image_ids=...` |

工具调用消息（`role=tool` 的中间步骤）**不写数据库**，只在当次 `handle_message` 内存中流转，循环结束即丢弃。

---

## 2. 跨轮压缩：识别摘要压缩

### 单张上传

上传时写两条消息：

```
assistant: "已识别图片，发现 2 处明确隐患：...(完整识别摘要，约 300 token)"
system:    "[context] 待确认图片 image_id=3"
```

一旦图片进入终态（`confirmed` 或 `corrected_submitted`），`_build_messages` 构建时：

- assistant 消息 → 替换为一行：`[图3·已确认] 共2条记录，明确隐患2处。如需详情请调用 get_session_hazards(image_id=3)。`（~30 token）
- system 上下文 → 替换为：`[已处理] image_id=3 状态:已确认`

**原始消息不删除**，仅在构建时动态压缩。

### 批量上传

批量上传只写**两条消息**（与图片数量无关）：

```
assistant: "已完成 5 张图识别，共发现：明确隐患 3 处..."（聚合摘要，约 150 token）
system:    "[context] 批量上传 image_ids=3,4,5,6,7"
```

当批次内**所有图片**均进入终态时，压缩为：

```
assistant: "[批量已处理] 共5张图片，全部已确认/已纠错。"
system:    "[已处理] 批量上传 全部已处理"
```

这彻底避免了批量上传后上下文随图片数量线性增长的问题。

### 压缩时机判断（代码路径）

`_build_messages` 第一遍扫描 `messages`，建立两个映射：

- `detect_msg`: `assistant_msg.id → image_id`（通过紧跟的 system 上下文）
- `completed`: 已进入终态的 `image_id` 集合

第二遍构建时，凡是 `detect_msg[m.id] in completed` 的 assistant 消息，就替换为压缩版本。

---

## 3. system 消息前置（OpenAI 兼容）

严格的 OpenAI/vLLM 端点要求 `system` 消息只能出现在 `position 0`。`_build_messages` 将所有 system 内容合并成一条，放在消息列表最前：

```python
system_parts = [SYSTEM_PROMPT]
# 追加各图片的 context（已处理/未处理状态）
return [{"role": "system", "content": "\n".join(system_parts)}] + convo
```

数据库里的 `role=system` 消息**不直接放进 convo**，而是提取内容追加到首条 system 消息的 `system_parts`。

---

## 4. 单轮截断：_trim_convo

当重建后的对话历史超过 `MAX_CONTEXT_CHARS`（默认 80,000 字符）时，从头截断旧消息：

```python
keep_from = max(0, len(convo) - _MIN_KEEP)   # _MIN_KEEP = 8，保底保留最近 8 条
# 从最老的消息开始丢弃，直到总字符数 <= 上限
```

**截断策略：**
- 优先丢弃最旧的消息
- 最近 8 条消息永远保留（保证 LLM 有足够上下文理解当前对话）
- 只截断 `convo`（user/assistant 对话），不截断 system 部分

配置项：

```
MAX_CONTEXT_CHARS=80000   # .env
```

---

## 5. 跨轮工具缓存

只读工具（`search_standards`、`query_statistics`）的调用结果在同一 session 内跨轮缓存，防止重复查询：

```python
_session_cross_caches: dict[str, set[str]] = {}
# key = json.dumps([tool_name, args])
```

- 缓存存在进程内存（`Orchestrator` 类外的模块级变量），进程重启后清空
- `ToolGuard.check()` 在执行工具前检查缓存，命中则返回 `guard_blocked`（跨轮缓存命中）
- 只缓存幂等的只读工具，`confirm_hazards`、`submit_correction` 等写操作不缓存

---

## 6. 工具调用消息的生命周期

```
handle_message 调用开始
        │
        ├── _build_messages() → 从 DB 重建历史，存入 state.messages（内存）
        │
        while 循环：
        ├── LLM 返回 tool_calls → 追加到 state.messages（内存）
        ├── 执行工具 → 结果追加到 state.messages（内存）
        │           └── _record_tool() → 写 tool_traces 表（持久化）
        │
        ├── LLM 返回纯文字 → 写 messages 表（持久化）
        └── _flush_traces() → 回填 tool_traces.loop_outcome
        │
handle_message 调用结束 → state.messages 销毁
```

工具调用的来回消息只存活于单次 `handle_message` 的 `state.messages` 列表中。下次用户发消息时，`_build_messages` 重新从 DB 构建，工具调用的中间步骤不会出现在新的上下文里。

---

## 7. 相关配置

| 配置项 | 默认值 | 作用 |
|---|---|---|
| `MAX_CONTEXT_CHARS` | `80000` | 发给模型前历史消息的字符上限 |
| `MAX_TOOL_ITERATIONS` | `5` | 单次问答最多连续调用工具次数 |
| `TOOL_LOOP_TIMEOUT_SECONDS` | `30` | 单次问答工具循环超时秒数 |
| `AGENT_DEBUG_DIR` | `runtime/debug` | LLM 原始调用日志目录，空字符串禁用 |

---

## 8. 诊断与排查

**查看某 session 的完整消息历史：**

```sql
SELECT role, substr(content, 1, 100), created_at
FROM messages
WHERE session_id = 'xxx'
ORDER BY id;
```

**查看上下文压缩是否生效（已确认图片的消息应该很短）：**

```python
# 实时重建看压缩后的内容
from app.agent.orchestrator import Orchestrator
# ...构建 orch 后
msgs = orch._build_messages('your_session_id')
for m in msgs:
    print(m['role'], len(m.get('content', '')), m.get('content', '')[:80])
```

**查看工具调用是否被跨轮缓存命中：**

```sql
SELECT tool_name, outcome, result_summary
FROM tool_traces
WHERE session_id = 'xxx' AND outcome = 'guard_blocked';
```

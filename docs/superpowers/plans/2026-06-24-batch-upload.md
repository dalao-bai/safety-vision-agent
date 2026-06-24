# Batch Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `POST /sessions/{sid}/images/batch` with parallel VLM detection, aggregate context messages, `confirm_hazards_batch` tool, and `_build_messages` compression for batch uploads.

**Architecture:** The API route validates/saves files, runs VLM in parallel via `ThreadPoolExecutor`, then calls `Orchestrator.handle_batch_images` which writes DB records and exactly two aggregate messages. `_build_messages` gains a `_BATCH_CTX_PREFIX` branch that compresses those messages once all images reach a terminal state.

**Tech Stack:** Python 3.11+, FastAPI, SQLite (`app.persistence.db.Database`), `concurrent.futures.ThreadPoolExecutor`, pydantic-settings, pytest

---

## File Map

| File | Change |
|---|---|
| `backend/app/persistence/db.py` | Add `get_pending_image_ids(session_id)` |
| `backend/app/config.py` | Add `max_vlm_workers: int = 4` |
| `backend/app/agent/tools.py` | Add `confirm_hazards_batch` schema + dispatch; add `status_filter` to `get_session_hazards` dispatch |
| `backend/app/agent/prompts.py` | Append rule 6 (batch upload behaviour) to `SYSTEM_PROMPT` |
| `backend/app/agent/orchestrator.py` | Add `handle_batch_images`; update `_build_messages` for `_BATCH_CTX_PREFIX` |
| `backend/app/api/images.py` | Extract `_save_upload` helper; add `POST /sessions/{sid}/images/batch` route |
| `backend/tests/test_db.py` | Add `test_get_pending_image_ids` |
| `backend/tests/test_tools.py` | Update schema coverage test; add `confirm_hazards_batch` + `status_filter` tests |
| `backend/tests/test_prompts.py` | Add `test_system_prompt_has_batch_rules` |
| `backend/tests/test_orchestrator.py` | Add `test_handle_batch_images_*`; add `test_build_messages_batch_compression` |
| `backend/tests/test_api.py` | Add batch upload integration tests |

---

### Task 1: DB — `get_pending_image_ids`

**Files:**
- Modify: `backend/app/persistence/db.py`
- Test: `backend/tests/test_db.py`

- [ ] **Step 1: Write the failing test**

Add to the bottom of `backend/tests/test_db.py`:

```python
def test_get_pending_image_ids(tmp_path: Path):
    db = Database(str(tmp_path / "t.db"))
    sid = db.create_session()
    img1 = db.add_image(sid, "p1.png", "s")
    img2 = db.add_image(sid, "p2.png", "s")
    img3 = db.add_image(sid, "p3.png", "s")
    db.set_image_status(img2, "confirmed")

    pending = db.get_pending_image_ids(sid)
    assert sorted(pending) == sorted([img1, img3])

    # cross-session isolation: other session's image not returned
    sid2 = db.create_session()
    img4 = db.add_image(sid2, "p4.png", "s")
    assert img4 not in db.get_pending_image_ids(sid)
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd backend && python -m pytest tests/test_db.py::test_get_pending_image_ids -v
```

Expected: `AttributeError: 'Database' object has no attribute 'get_pending_image_ids'`

- [ ] **Step 3: Implement**

In `backend/app/persistence/db.py`, add after `mark_hazards_confirmed`:

```python
    def get_pending_image_ids(self, session_id: int) -> list[int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM images WHERE session_id=? AND status='awaiting_confirmation'",
                (session_id,),
            ).fetchall()
        return [r[0] for r in rows]
```

- [ ] **Step 4: Run to confirm pass**

```bash
cd backend && python -m pytest tests/test_db.py::test_get_pending_image_ids -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add backend/app/persistence/db.py backend/tests/test_db.py
git commit -m "feat(db): add get_pending_image_ids"
```

---

### Task 2: Config — `max_vlm_workers`

**Files:**
- Modify: `backend/app/config.py`

- [ ] **Step 1: Add field**

In `backend/app/config.py`, add `max_vlm_workers` immediately after `max_tool_iterations`:

```python
    max_tool_iterations: int = 5
    max_vlm_workers: int = 4
```

- [ ] **Step 2: Verify existing tests pass**

```bash
cd backend && python -m pytest tests/test_config.py -v
```

Expected: all `PASSED`

- [ ] **Step 3: Commit**

```bash
git add backend/app/config.py
git commit -m "feat(config): add max_vlm_workers (default 4)"
```

---

### Task 3: Tools — `confirm_hazards_batch` + `status_filter`

**Files:**
- Modify: `backend/app/agent/tools.py`
- Test: `backend/tests/test_tools.py`

- [ ] **Step 1: Write failing tests**

In `backend/tests/test_tools.py`, update the existing `test_schemas_cover_all_tools` assertion to include `confirm_hazards_batch`:

```python
def test_schemas_cover_all_tools():
    names = {t["function"]["name"] for t in TOOL_SCHEMAS}
    assert names == {"query_kg", "search_standards", "get_session_hazards",
                     "submit_correction", "export_report", "confirm_hazards",
                     "query_statistics", "confirm_hazards_batch"}
```

Then add new tests at the bottom:

```python
def test_confirm_hazards_batch_by_ids(tmp_path, kg_path):
    ctx, img_id = _ctx(tmp_path, kg_path)
    out = dispatch_tool("confirm_hazards_batch", {"image_ids": [img_id]}, ctx)
    assert out["ok"] is True
    assert out["confirmed_count"] == 1
    assert img_id in out["image_ids"]
    assert ctx.db.get_image(img_id).status == "confirmed"
    assert ctx.db.get_hazards(img_id)[0].confirmed is True


def test_confirm_hazards_batch_confirm_all(tmp_path, kg_path):
    ctx, img_id = _ctx(tmp_path, kg_path)
    img2 = ctx.db.add_image(ctx.session_id, "p2.png", "s")
    ctx.db.add_hazards(img2, [{"object_id": "foundation_pit_edge_protection",
                               "status": "confirmed_hazard", "hazard_type_id": "missing_protection",
                               "bbox": [1, 2, 3, 4], "reasoning_chain": [],
                               "visual_evidence": "e", "rule_basis": "r",
                               "evidence_sufficiency": "sufficient"}])
    out = dispatch_tool("confirm_hazards_batch", {"confirm_all": True}, ctx)
    assert out["confirmed_count"] == 2
    assert sorted(out["image_ids"]) == sorted([img_id, img2])


def test_confirm_hazards_batch_cross_session_blocked(tmp_path, kg_path):
    ctx, _ = _ctx(tmp_path, kg_path)
    other_sid = ctx.db.create_session()
    other_img = ctx.db.add_image(other_sid, "other.png", "s")
    out = dispatch_tool("confirm_hazards_batch", {"image_ids": [other_img]}, ctx)
    assert other_img not in out["image_ids"]
    assert out["confirmed_count"] == 0


def test_get_session_hazards_status_filter(tmp_path, kg_path):
    ctx, img_id = _ctx(tmp_path, kg_path)
    ctx.db.add_hazards(img_id, [{"object_id": "stair_opening_protection",
                                 "status": "uncertain", "hazard_type_id": None,
                                 "bbox": None, "reasoning_chain": [],
                                 "visual_evidence": "e", "rule_basis": "r",
                                 "evidence_sufficiency": "insufficient"}])
    out_confirmed = dispatch_tool("get_session_hazards", {"status_filter": "confirmed_hazard"}, ctx)
    assert all(h["status"] == "confirmed_hazard" for h in out_confirmed["hazards"])
    out_uncertain = dispatch_tool("get_session_hazards", {"status_filter": "uncertain"}, ctx)
    assert all(h["status"] == "uncertain" for h in out_uncertain["hazards"])
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd backend && python -m pytest tests/test_tools.py::test_schemas_cover_all_tools tests/test_tools.py::test_confirm_hazards_batch_by_ids -v
```

Expected: both `FAILED`

- [ ] **Step 3: Append `confirm_hazards_batch` to `TOOL_SCHEMAS`**

In `backend/app/agent/tools.py`, add this entry to `TOOL_SCHEMAS` before the closing `]`:

```python
    {"type": "function", "function": {
        "name": "confirm_hazards_batch",
        "description": "批量确认多张图片的识别结果。image_ids 传具体列表，或 confirm_all=true 确认本会话全部待确认图片。",
        "parameters": {"type": "object", "properties": {
            "image_ids": {"type": "array", "items": {"type": "integer"},
                          "description": "要确认的图片 id 列表"},
            "confirm_all": {"type": "boolean",
                            "description": "true 时确认本会话全部待确认图片"},
        }}}},
```

- [ ] **Step 4: Add `status_filter` parameter to `get_session_hazards` schema**

In `backend/app/agent/tools.py`, replace the `get_session_hazards` entry in `TOOL_SCHEMAS`:

```python
    {"type": "function", "function": {
        "name": "get_session_hazards",
        "description": "召回本会话已识别的隐患(多轮记忆)。传 image_id 时返回该图完整字段；不传时返回会话级摘要（长文本截断，最多 limit 条）。",
        "parameters": {"type": "object", "properties": {
            "image_id": {"type": "integer"},
            "limit": {"type": "integer", "description": "会话级查询最多返回条数，默认 20"},
            "status_filter": {"type": "string",
                              "description": "可选过滤：uncertain / confirmed_hazard / safe"},
        }}}},
```

- [ ] **Step 5: Add `confirm_hazards_batch` dispatch handler**

In `backend/app/agent/tools.py` inside `dispatch_tool`, add before the final `raise ValueError`:

```python
    if name == "confirm_hazards_batch":
        if args.get("confirm_all"):
            ids = ctx.db.get_pending_image_ids(ctx.session_id)
        else:
            ids = [int(i) for i in args.get("image_ids", [])]
        ids = [i for i in ids if _owns_image(ctx, i)]
        for img_id in ids:
            ctx.db.mark_hazards_confirmed(img_id)
            ctx.db.set_image_status(img_id, "confirmed")
        return {"ok": True, "confirmed_count": len(ids), "image_ids": ids}
```

- [ ] **Step 6: Add `status_filter` to `get_session_hazards` dispatch**

In `backend/app/agent/tools.py`, replace the `if name == "get_session_hazards":` block:

```python
    if name == "get_session_hazards":
        img_id = args.get("image_id")
        if img_id:
            if not _owns_image(ctx, int(img_id)):
                return {"hazards": [], "error": f"image {img_id} not in this session"}
            hz = ctx.db.get_hazards(int(img_id))
            return {"hazards": [_hazard_brief(h, full=True) for h in hz]}
        else:
            limit = max(1, min(int(args.get("limit", 20)), 50))
            status_filter = args.get("status_filter")
            all_hz = ctx.db.get_session_hazards(ctx.session_id)
            if status_filter:
                all_hz = [h for h in all_hz if h.status == status_filter]
            return {"total": len(all_hz), "returned": min(len(all_hz), limit),
                    "hazards": [_hazard_brief(h, full=False) for h in all_hz[:limit]]}
```

- [ ] **Step 7: Run all tool tests**

```bash
cd backend && python -m pytest tests/test_tools.py -v
```

Expected: all `PASSED`

- [ ] **Step 8: Commit**

```bash
git add backend/app/agent/tools.py backend/tests/test_tools.py
git commit -m "feat(tools): add confirm_hazards_batch + status_filter for get_session_hazards"
```

---

### Task 4: Prompts — rule 6

**Files:**
- Modify: `backend/app/agent/prompts.py`
- Test: `backend/tests/test_prompts.py`

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_prompts.py`:

```python
def test_system_prompt_has_batch_rules():
    assert "confirm_hazards_batch" in SYSTEM_PROMPT
    assert "confirm_all=true" in SYSTEM_PROMPT
    assert "status_filter" in SYSTEM_PROMPT
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd backend && python -m pytest tests/test_prompts.py::test_system_prompt_has_batch_rules -v
```

Expected: `FAILED`

- [ ] **Step 3: Append rule 6**

In `backend/app/agent/prompts.py`, replace the `SYSTEM_PROMPT` string with:

```python
SYSTEM_PROMPT = """你是「四口五临边」建筑安全隐患问答助手。规则:
1. 用户上传的图片已由专用视觉模型识别,识别结果作为事实依据,你不要重新臆测图像内容。
2. 当某张图处于「待确认」状态时,先围绕「识别结果是否正确」与用户交互:
   - 用户表示正确 → 调用 confirm_hazards(image_id) 将该图隐患标记为已确认,再简要确认并转入问答。
   - 用户表示不正确 → 先追问「具体哪里不正确」,拿到说明后调用 submit_correction(image_id, note) 工具记录并入队,再告知已记录。
3. 回答标准/整改类问题时,用工具获取依据后再作答,并引用出处:
   - query_kg:取防护对象/隐患类型的定义、合格条件(整改依据)、规则块、标准出处。
   - search_standards:在 JGJ 标准原文中检索条文。
   - get_session_hazards:回顾本会话已识别隐患(支持「刚才那张图」之类指代)。
   - export_report:导出 Markdown 报告。
   - query_statistics:统计全库(跨会话)隐患数量;当用户询问某天/某时段隐患总数、某类别数量或频率排名时使用;date_from/date_to 格式 YYYY-MM-DD,不传则不限时间范围。
4. 整改建议基于 query_kg 返回的 qualified_conditions(合格条件)或 rule_blocks 给出可操作项。
5. 不编造标准条文与编号;检索不到时如实说明并给出 KG 内依据。
6. 批量上传场景:
   - 识别完成后的聚合摘要已包含统计信息,无需再逐张复述。
   - 用户说「全部确认」→ 调用 confirm_hazards_batch(confirm_all=true)。
   - 用户指定部分确认 → 调用 confirm_hazards_batch(image_ids=[...])。
   - 用户要看某张详情 → 调用 get_session_hazards(image_id=X)。
   - 用户要看证据不足的 → 调用 get_session_hazards(status_filter="uncertain")。
"""
```

- [ ] **Step 4: Run to confirm pass**

```bash
cd backend && python -m pytest tests/test_prompts.py -v
```

Expected: all `PASSED`

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/prompts.py backend/tests/test_prompts.py
git commit -m "feat(prompts): add rule 6 for batch upload scenario"
```

---

### Task 5: Orchestrator — `handle_batch_images`

**Files:**
- Modify: `backend/app/agent/orchestrator.py`
- Test: `backend/tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/test_orchestrator.py`:

```python
def test_handle_batch_images_success(tmp_path, kg_path):
    orch, db, _ = _orch(tmp_path, kg_path, [])
    sid = db.create_session()
    succeeded = [("p1.png", _sample_result()), ("p2.png", _sample_result())]

    result = orch.handle_batch_images(sid, succeeded, failed_files=[])

    assert result["succeeded"] == 2
    assert result["failed"] == 0
    assert result["total"] == 2
    assert result["summary"]["confirmed_hazard"] == 2
    assert "已完成 2 张图识别" in result["assistant_message"]

    msgs = db.get_messages(sid)
    assert [m.role for m in msgs] == ["assistant", "system"]
    assert msgs[1].content.startswith("[context] 批量上传 image_ids=")


def test_handle_batch_images_partial_failure(tmp_path, kg_path):
    orch, db, _ = _orch(tmp_path, kg_path, [])
    sid = db.create_session()

    result = orch.handle_batch_images(
        sid,
        succeeded=[("p1.png", _sample_result())],
        failed_files=[{"filename": "p2.png", "reason": "vlm_error"}],
    )

    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert result["total"] == 2
    msgs = db.get_messages(sid)
    assert any(m.content.startswith("[context] 批量上传 image_ids=") for m in msgs)
    assert "失败" in result["assistant_message"]


def test_handle_batch_images_all_failed(tmp_path, kg_path):
    orch, db, _ = _orch(tmp_path, kg_path, [])
    sid = db.create_session()

    result = orch.handle_batch_images(
        sid,
        succeeded=[],
        failed_files=[
            {"filename": "p1.png", "reason": "vlm_error"},
            {"filename": "p2.png", "reason": "vlm_error"},
        ],
    )

    assert result["succeeded"] == 0
    assert result["failed"] == 2
    assert result["total"] == 2
    msgs = db.get_messages(sid)
    assert len(msgs) == 1
    assert msgs[0].role == "assistant"
    assert "失败" in msgs[0].content
    assert not any(m.content.startswith("[context] 批量上传 image_ids=") for m in msgs)
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd backend && python -m pytest tests/test_orchestrator.py::test_handle_batch_images_success -v
```

Expected: `AttributeError: 'Orchestrator' object has no attribute 'handle_batch_images'`

- [ ] **Step 3: Implement `handle_batch_images`**

In `backend/app/agent/orchestrator.py`, add after `handle_image`:

```python
    def handle_batch_images(
        self,
        session_id: int,
        succeeded: "list[tuple[str, DetectionResult]]",
        failed_files: "list[dict]",
    ) -> dict:
        image_ids: list[int] = []
        stats: dict[str, int] = {"confirmed_hazard": 0, "uncertain": 0, "safe": 0}

        for path, result in succeeded:
            img_id = self._db.add_image(session_id, path, result.scene)
            self._db.add_hazards(img_id, [{
                "object_id": h.object_id, "status": h.status,
                "hazard_type_id": h.hazard_type_id, "bbox": h.bbox,
                "reasoning_chain": h.reasoning_chain, "visual_evidence": h.visual_evidence,
                "rule_basis": h.rule_basis, "evidence_sufficiency": h.evidence_sufficiency,
                "uncertainty_reason": h.uncertainty_reason, "missing_evidence": h.missing_evidence,
            } for h in result.hazards])
            image_ids.append(img_id)
            for h in result.hazards:
                if h.status in stats:
                    stats[h.status] += 1

        total = len(succeeded) + len(failed_files)

        if image_ids:
            fail_note = ""
            if failed_files:
                names = "、".join(f["filename"] for f in failed_files[:5])
                if len(failed_files) > 5:
                    names += f" 等{len(failed_files)}张"
                fail_note = f"（{len(failed_files)} 张失败：{names}）"

            assistant_msg = (
                f"已完成 {len(succeeded)} 张图识别{fail_note}，共发现：\n\n"
                f"| 状态 | 数量 |\n|---|---|\n"
                f"| 明确隐患 | {stats['confirmed_hazard']} 处 |\n"
                f"| 证据不足 | {stats['uncertain']} 处 |\n"
                f"| 未见明显隐患 | {stats['safe']} 处 |\n\n"
                "如需查看某张图的详细结果，告诉我图片序号或 image_id；\n"
                "输入「全部确认」批量标记已确认，或指定「确认第 1、3、5 张」。"
            )
            system_ctx = f"[context] 批量上传 image_ids={','.join(str(i) for i in image_ids)}"
            self._db.add_message(session_id, "assistant", assistant_msg)
            self._db.add_message(session_id, "system", system_ctx)
        else:
            assistant_msg = (
                f"批量上传失败：全部 {total} 张图 VLM 识别出错，"
                "未生成任何隐患记录。请检查模型服务或重新上传。"
            )
            self._db.add_message(session_id, "assistant", assistant_msg)

        return {
            "total": total,
            "succeeded": len(succeeded),
            "failed": len(failed_files),
            "summary": stats,
            "failed_files": failed_files,
            "assistant_message": assistant_msg,
        }
```

- [ ] **Step 4: Run to confirm pass**

```bash
cd backend && python -m pytest tests/test_orchestrator.py::test_handle_batch_images_success tests/test_orchestrator.py::test_handle_batch_images_partial_failure tests/test_orchestrator.py::test_handle_batch_images_all_failed -v
```

Expected: all `PASSED`

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/orchestrator.py backend/tests/test_orchestrator.py
git commit -m "feat(orchestrator): add handle_batch_images"
```

---

### Task 6: Orchestrator — `_build_messages` batch compression

**Files:**
- Modify: `backend/app/agent/orchestrator.py`
- Test: `backend/tests/test_orchestrator.py`

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_orchestrator.py`:

```python
def test_build_messages_batch_compression(tmp_path, kg_path):
    orch, db, _ = _orch(tmp_path, kg_path, [])
    sid = db.create_session()
    orch.handle_batch_images(sid, [("p1.png", _sample_result()), ("p2.png", _sample_result())],
                             failed_files=[])
    ctx_msg = next(m for m in db.get_messages(sid)
                   if m.content.startswith("[context] 批量上传 image_ids="))
    img_ids = [int(x) for x in ctx_msg.content.split("=")[1].split(",")]

    # before confirmation: full summary visible
    built = orch._build_messages(sid)
    assert any("已完成" in m["content"] for m in built if m["role"] == "assistant")

    for img_id in img_ids:
        db.mark_hazards_confirmed(img_id)
        db.set_image_status(img_id, "confirmed")

    # after confirmation: summary compressed
    built2 = orch._build_messages(sid)
    asst = [m["content"] for m in built2 if m["role"] == "assistant"]
    assert any("[批量已处理]" in c for c in asst)
    assert not any("已完成" in c for c in asst)
    sys_content = built2[0]["content"]
    assert "[已处理] 批量上传" in sys_content
    assert "[context] 批量上传 image_ids=" not in sys_content
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd backend && python -m pytest tests/test_orchestrator.py::test_build_messages_batch_compression -v
```

Expected: `FAILED` — no `[批量已处理]` after confirmation

- [ ] **Step 3: Add `_BATCH_CTX_PREFIX` constant**

In `backend/app/agent/orchestrator.py`, add after `_CTX_PREFIX`:

```python
_BATCH_CTX_PREFIX = "[context] 批量上传 image_ids="
```

- [ ] **Step 4: Replace `_build_messages` first pass**

Replace lines from `detect_msg: dict[int, int] = {}` through the end of the first `for m in raw:` loop with:

```python
        detect_msg: dict[int, int] = {}
        completed: set[int] = set()
        batch_asst_to_ids: dict[int, list[int]] = {}
        batch_ctx_compressed: set[int] = set()
        prev_asst = None
        for m in raw:
            if m.role == "assistant":
                prev_asst = m
            elif m.role == "system" and m.content.startswith(_CTX_PREFIX):
                img_id = int(m.content[len(_CTX_PREFIX):].strip())
                if prev_asst is not None:
                    detect_msg[prev_asst.id] = img_id
                    try:
                        if self._db.get_image(img_id).status in ("confirmed", "corrected_submitted"):
                            completed.add(img_id)
                    except KeyError:
                        pass
                prev_asst = None
            elif m.role == "system" and m.content.startswith(_BATCH_CTX_PREFIX):
                ids_str = m.content[len(_BATCH_CTX_PREFIX):]
                batch_ids = [int(x) for x in ids_str.split(",") if x.strip().isdigit()]
                if prev_asst is not None and batch_ids:
                    try:
                        all_terminal = all(
                            self._db.get_image(i).status in ("confirmed", "corrected_submitted")
                            for i in batch_ids
                        )
                    except KeyError:
                        all_terminal = False
                    if all_terminal:
                        batch_asst_to_ids[prev_asst.id] = batch_ids
                        batch_ctx_compressed.add(m.id)
                prev_asst = None
            else:
                prev_asst = None
```

- [ ] **Step 5: Replace `_build_messages` second pass**

Replace lines from `system_parts = [SYSTEM_PROMPT]` through `return [...]` with:

```python
        system_parts = [SYSTEM_PROMPT]
        convo: list[dict[str, Any]] = []
        for m in raw:
            if m.role == "system":
                if m.content.startswith(_CTX_PREFIX):
                    img_id = int(m.content[len(_CTX_PREFIX):].strip())
                    if img_id in completed:
                        img = self._db.get_image(img_id)
                        system_parts.append(_compress_system_ctx(img_id, img.status))
                    else:
                        system_parts.append(m.content)
                elif m.content.startswith(_BATCH_CTX_PREFIX):
                    if m.id in batch_ctx_compressed:
                        system_parts.append("[已处理] 批量上传 全部已处理")
                    else:
                        system_parts.append(m.content)
                else:
                    system_parts.append(m.content)
            elif m.role in ("user", "assistant"):
                if m.id in detect_msg and detect_msg[m.id] in completed:
                    img_id = detect_msg[m.id]
                    img = self._db.get_image(img_id)
                    hz = self._db.get_hazards(img_id)
                    convo.append({"role": "assistant",
                                  "content": _compress_assistant_msg(img_id, img.status, hz)})
                elif m.id in batch_asst_to_ids:
                    n = len(batch_asst_to_ids[m.id])
                    convo.append({"role": "assistant",
                                  "content": f"[批量已处理] 共{n}张图片，全部已确认/已纠错。"})
                else:
                    convo.append({"role": m.role, "content": m.content})

        return [{"role": "system", "content": "\n".join(system_parts)}] + convo
```

- [ ] **Step 6: Run all orchestrator tests**

```bash
cd backend && python -m pytest tests/test_orchestrator.py -v
```

Expected: all `PASSED`

- [ ] **Step 7: Commit**

```bash
git add backend/app/agent/orchestrator.py backend/tests/test_orchestrator.py
git commit -m "feat(orchestrator): _build_messages batch compression via _BATCH_CTX_PREFIX"
```

---

### Task 7: API — `POST /sessions/{sid}/images/batch`

**Files:**
- Modify: `backend/app/api/images.py`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/test_api.py`:

```python
def test_batch_upload_success(client):
    c, tiny_png = client
    sid = c.post("/sessions").json()["session_id"]
    png_bytes = tiny_png.read_bytes()

    r = c.post(f"/sessions/{sid}/images/batch", files=[
        ("files", ("a.png", png_bytes, "image/png")),
        ("files", ("b.png", png_bytes, "image/png")),
    ])
    assert r.status_code == 200
    body = r.json()
    assert body["succeeded"] == 2
    assert body["failed"] == 0
    assert body["total"] == 2
    assert "batch_id" in body
    assert "已完成 2 张图识别" in body["assistant_message"]


def test_batch_upload_invalid_type_skipped(client):
    c, tiny_png = client
    sid = c.post("/sessions").json()["session_id"]

    r = c.post(f"/sessions/{sid}/images/batch", files=[
        ("files", ("a.png", tiny_png.read_bytes(), "image/png")),
        ("files", ("b.pdf", b"not-a-pdf", "application/pdf")),
    ])
    assert r.status_code == 200
    body = r.json()
    assert body["succeeded"] == 1
    assert body["failed"] == 1
    assert body["failed_files"][0]["reason"] == "unsupported_type"


def test_batch_upload_all_invalid_returns_422(client):
    c, _ = client
    sid = c.post("/sessions").json()["session_id"]
    r = c.post(f"/sessions/{sid}/images/batch", files=[
        ("files", ("a.pdf", b"x", "application/pdf")),
    ])
    assert r.status_code == 422


def test_batch_upload_unknown_session_404(client):
    c, tiny_png = client
    r = c.post("/sessions/9999/images/batch", files=[
        ("files", ("a.png", tiny_png.read_bytes(), "image/png")),
    ])
    assert r.status_code == 404
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd backend && python -m pytest tests/test_api.py::test_batch_upload_success -v
```

Expected: `404` (route does not exist)

- [ ] **Step 3: Replace `backend/app/api/images.py`**

```python
from __future__ import annotations

import hashlib
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

import app.api.deps as deps
from app.agent.orchestrator import Orchestrator
from app.agent.tools import ToolContext
from app.config import get_settings
from app.vlm.detector import DetectionError

router = APIRouter()

_ALLOWED = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def _save_upload(data: bytes, sid: int, suffix: str, upload_dir: Path) -> str:
    upload_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(data).hexdigest()[:16]
    dest = (upload_dir / f"{sid}_{digest}{suffix}").resolve()
    if not dest.is_relative_to(upload_dir.resolve()):
        raise ValueError("invalid path")
    dest.write_bytes(data)
    return str(dest)


def _make_orch(db, agent_client, kg, standards, intake, settings) -> tuple:
    ctx_factory = lambda session_id: ToolContext(
        db=db, kg=kg, standards=standards, intake=intake,
        report_dir=settings.report_dir, session_id=session_id)
    orch = Orchestrator(db=db, agent_client=agent_client, agent_model=settings.agent_model,
                        ctx_factory=ctx_factory, max_iterations=settings.max_tool_iterations)
    return orch, ctx_factory


@router.post("/sessions/{sid}/images")
def upload_image(sid: int, file: UploadFile = File(...),
                 db=Depends(deps.get_db), kg=Depends(deps.get_kg),
                 detector=Depends(deps.get_detector),
                 agent_client=Depends(deps.get_agent_client),
                 intake=Depends(deps.get_intake),
                 standards=Depends(deps.get_standards)):
    if not db.session_exists(sid):
        raise HTTPException(404, "session not found")
    settings = get_settings()
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED:
        raise HTTPException(400, f"unsupported image type: {suffix}")
    data = file.file.read(settings.max_image_bytes + 1)
    if len(data) > settings.max_image_bytes:
        raise HTTPException(413, "image too large")

    path = _save_upload(data, sid, suffix, Path(settings.upload_dir))
    try:
        result = detector.detect(path)
    except DetectionError as exc:
        raise HTTPException(422, f"识别失败: {exc}")

    orch, _ = _make_orch(db, agent_client, kg, standards, intake, settings)
    img_id = orch.handle_image(sid, path, result)
    msgs = db.get_messages(sid)
    assistant_message = next((m.content for m in reversed(msgs) if m.role == "assistant"), "")
    return {"image_id": img_id, "scene": result.scene,
            "hazards": [{"object_id": h.object_id, "object_name": h.object_name, "status": h.status,
                         "hazard_type_id": h.hazard_type_id, "bbox": h.bbox,
                         "visual_evidence": h.visual_evidence} for h in result.hazards],
            "assistant_message": assistant_message}


@router.post("/sessions/{sid}/images/batch")
def upload_batch_images(
    sid: int,
    files: List[UploadFile] = File(...),
    db=Depends(deps.get_db),
    kg=Depends(deps.get_kg),
    detector=Depends(deps.get_detector),
    agent_client=Depends(deps.get_agent_client),
    intake=Depends(deps.get_intake),
    standards=Depends(deps.get_standards),
):
    if not db.session_exists(sid):
        raise HTTPException(404, "session not found")
    settings = get_settings()
    upload_dir = Path(settings.upload_dir)

    valid: list[tuple[str, str]] = []  # (original_filename, dest_path)
    failed_files: list[dict] = []

    for f in files:
        suffix = Path(f.filename or "").suffix.lower()
        if suffix not in _ALLOWED:
            failed_files.append({"filename": f.filename or "", "reason": "unsupported_type"})
            continue
        data = f.file.read(settings.max_image_bytes + 1)
        if len(data) > settings.max_image_bytes:
            failed_files.append({"filename": f.filename or "", "reason": "file_too_large"})
            continue
        try:
            path = _save_upload(data, sid, suffix, upload_dir)
        except ValueError:
            failed_files.append({"filename": f.filename or "", "reason": "invalid_path"})
            continue
        valid.append((f.filename or "", path))

    if not valid:
        raise HTTPException(422, "所有文件均无效，请检查文件类型和大小")

    def _detect_one(item: tuple[str, str]):
        filename, path = item
        try:
            return filename, path, detector.detect(path), None
        except Exception as exc:
            return filename, path, None, str(exc)

    with ThreadPoolExecutor(max_workers=settings.max_vlm_workers) as pool:
        outcomes = list(pool.map(_detect_one, valid))

    succeeded = [(path, result) for _, path, result, _ in outcomes if result is not None]
    for filename, _, result, _ in outcomes:
        if result is None:
            failed_files.append({"filename": filename, "reason": "vlm_error"})

    orch, _ = _make_orch(db, agent_client, kg, standards, intake, settings)
    response = orch.handle_batch_images(sid, succeeded, failed_files)
    response["batch_id"] = str(uuid.uuid4())
    return response
```

- [ ] **Step 4: Run all API tests**

```bash
cd backend && python -m pytest tests/test_api.py -v
```

Expected: all `PASSED`

- [ ] **Step 5: Run full test suite**

```bash
cd backend && python -m pytest -v
```

Expected: all `PASSED` (all prior tests + new batch tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/images.py backend/tests/test_api.py
git commit -m "feat(api): POST /sessions/{sid}/images/batch with parallel VLM and aggregate context"
```

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| §2.2 `batch_id` UUID, not persisted | Task 7 — `uuid.uuid4()` in route, not written to DB |
| §2.3 跳过无效文件（类型/大小）| Task 7 — suffix + size check, skip to `failed_files` |
| §2.3 全部无效返回 422 | Task 7 — `if not valid: raise HTTPException(422, ...)` |
| §2.3 ThreadPoolExecutor 并发 VLM | Task 7 — `ThreadPoolExecutor(max_workers=settings.max_vlm_workers)` |
| §2.3 DB 写入在 ThreadPool 结束后 | Task 5 — `handle_batch_images` called after `pool.map` completes |
| §2.4 聚合 assistant 消息 | Task 5 — `handle_batch_images` generates aggregate |
| §2.4 system context `_BATCH_CTX_PREFIX` format | Task 5 — `f"[context] 批量上传 image_ids={...}"` |
| §2.4 全部失败 HTTP 200 + 失败 assistant 消息 | Task 5 (succeeded=0 branch) + Task 7 (returns 200) |
| §2.5 `confirm_hazards_batch` 工具 | Task 3 — schema + dispatch |
| §2.5 `get_pending_image_ids` | Task 1 — DB method |
| §2.5 `status_filter` for `get_session_hazards` | Task 3 — schema + dispatch update |
| §2.6 system prompt rule 6 | Task 4 |
| §2.7 `_build_messages` 批量压缩 | Task 6 |
| §2.8 单张压缩逻辑不受影响 | Task 6 — existing `_CTX_PREFIX` branches preserved verbatim |
| `max_vlm_workers` config | Task 2 |

All requirements covered. ✓

**Placeholder scan:** No TBDs, no "implement later", no "add appropriate X". Every step has executable code. ✓

**Type consistency:**
- `handle_batch_images(session_id, succeeded, failed_files)` — defined Task 5, called Task 7 ✓
- `_save_upload(data, sid, suffix, upload_dir)` — defined Task 7 Step 3, used in both routes ✓
- `get_pending_image_ids(session_id)` — defined Task 1, used in Task 3 dispatch ✓
- `_BATCH_CTX_PREFIX` — defined Task 6 Step 3, used Task 6 Steps 4 & 5 ✓
- `batch_asst_to_ids`, `batch_ctx_compressed` — initialised Task 6 Step 4 first pass, consumed Task 6 Step 5 second pass ✓

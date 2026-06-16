# 设计：把「分析不准确」反馈接入标注流水线

Date: 2026-06-16
Status: 待评审

## 背景与动机

本仓库的上级项目目标是**微调一个「四口五临边」施工安全检测 VLM**。仓库里已有一套独立的
标注流水线 `annotation_pipeline/`（API 辅助预标注 → 浏览器人工复核 → 提交为训练 JSONL），
以及配套的知识图谱规则文件 `知识图谱主文件/four_openings_edges_rule_blocks.json`（65 条规则，
9 类对象 + 6 类隐患，已校验可被 `RuleStore.load` 直接加载）。

与此同时，agent 后端已经有一个「用户说不对」的信号通道：前端在每张图分析后让用户逐张确认，
不准确的图经 `POST /api/analyses/confirm` 写入 `runtime/annotation.db`（见 `analyses.py` 的
inaccurate 分支）。这个确认流程是**前端 UI 直调、刻意不经 LLM**的（v0.2 设计文档明确，为可靠性）。

**目标**：让「用户标记某图分析不准确」这个已有事件，**额外**自动触发标注流水线的**草标**阶段，
把这张图送上"通往训练数据"的轨道。复核与入库沿用流水线现有的人工流程，不改动。

**这不是什么**（澄清，避免套错形态）：
- 不是 LangGraph **tool**——触发是 UI 按钮、确定性动作，不该交给对话 LLM 即兴决定；且任务重、
  异步、带人工环节，不适合塞进对话工具。
- 不是 Claude Code **skill**——skill 是开发期给编码助手用的，不是上线产品（FastAPI+React，
  运行时无 Claude）的部件。
- **本质是一个普通后端功能：事件 → 后台任务**，与项目已有的 `_run_preference_update`、
  `_run_report`（均由 `BackgroundTasks` 触发）同款。

## 决策摘要（已与用户确认）

| 维度 | 决定 |
|---|---|
| 自动化范围 | 自动只到**草标**；复核(`--serve-review`)与提交(`--commit-reviewed`)仍为人工 |
| agent 旧分析 | 仅作**触发信号**；流水线对图重新推理（两套 schema 无法无损互转） |
| 触发方式 | 点「不对」→ 后端 `BackgroundTasks` 异步逐张跑，不阻塞 confirm 响应 |
| 标注模型 | **复用 agent `.env` 同一套 API**（`OPENAI_API_BASE_URL`/`OPENAI_API_KEY`/`VLM_MODEL`） |
| 触发入口 | **仅按钮**（不加对话 tool 入口） |
| 调用方式 | **子进程**调用流水线 CLI，不 import 进 FastAPI 进程 |

### 为什么用子进程而非 import

流水线是独立 CLI：用相对导入（`from .review_records import …`，须 `python -m` 运行）、在
`image_utils.py` 模块加载时改 `sys.path` 注入 `.python_deps`、`api_client.py` 内有 `time.sleep`
阻塞重试、并大量 `print`。import 进来会污染 agent 进程并阻塞 worker 线程；子进程天然隔离，
且**零改动流水线代码**（符合"保留既有模块"的原则）。

## 架构与数据流

```
用户前端点「这张分析不对」
        │
        ▼
POST /api/analyses/confirm        （已有端点，UI 直调，不经 LLM）
        │
        ├── (已有) 不准确图 → runtime/annotation.db
        ├── (已有) 准确图   → user_hazard_stats 统计；全部准确则触发偏好更新
        │
        └── (新增) 若 annotation_pipeline_enabled 且存在不准确图：
                    background_tasks.add_task(run_for_images, settings.database_path, settings, image_ids)
                                │
                                ▼
        annotation_pipeline_bridge.run_for_images()       （新增桥接模块）
          自开 DB 连接（请求期连接已关闭，复刻 _run_report 模式）
          规则文件缺失 → 记日志跳过；否则 ensure_api_config()
          逐个 image_id：get_image_by_id → stored_path → 子进程：
            python -m annotation_pipeline.cli
              --single-image <stored_path>
              --config       runtime/annotation_pipeline/api_config.json   （由 .env 生成）
              --rule-blocks  知识图谱主文件/four_openings_edges_rule_blocks.json
              --output-dir   runtime/annotation_pipeline_outputs
          （cwd=仓库根；失败只记日志，绝不上抛）
                                │
                                ▼
        草标产物：draft_json/ · boxed_review/ · review_decisions/*.review.json · raw_response/
                                │
        ——————————— 以下沿用流水线现有人工流程，本设计不改 ———————————
        人工复核：python -m annotation_pipeline.cli --serve-review --output-dir runtime/annotation_pipeline_outputs
        提交入库：python -m annotation_pipeline.cli --commit-reviewed --append-to-db
                                │
                                ▼
        accepted_records/images.jsonl + objects.jsonl   → 训练数据
```

## 组件与文件改动

全部为新增或最小侵入；默认开关关闭，**对现有 154 个测试零影响**。

### 1. 新增 `backend/app/services/annotation_pipeline_bridge.py`

桥接核心，对外暴露后台任务体与配置生成：

- `_repo_root() -> Path`：`Path(__file__).resolve().parents[3]`（已验证 = 仓库根）。
- `ensure_api_config(settings) -> Path`：把 `.env` 设置写成
  `runtime/annotation_pipeline/api_config.json`，内容
  `{"api_endpoint": openai_api_base_url, "api_key": openai_api_key, "model": vlm_model}`，
  文件权限设 `0o600`，返回路径。
- `run_for_images(db_path, settings, image_ids)`：**后台任务体**。
  - 自开 `connect(db_path)` + `init_db`（复刻 `report.py:_run_report` / `analyses.py:_run_preference_update`）。
  - 解析规则文件路径（相对则相对仓库根）；不存在 → `logger.warning` 后 return（优雅降级）。
  - `ensure_api_config(settings)`。
  - 逐个 `image_id`：`repo.get_image_by_id` → `stored_path`；文件不存在 → 记日志跳过；
    否则调 `_run_pipeline_single(...)`。
  - `finally: conn.close()`。整体 `try/except` 兜底，绝不抛异常。
- `_run_pipeline_single(repo_root, settings, image_path, config_path)`：
  - `cmd = [sys.executable, "-m", "annotation_pipeline.cli", "--single-image", str(image_path),
    "--config", str(config_path), "--rule-blocks", str(rule_path),
    "--output-dir", str(output_dir)]`
  - `subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT_SECONDS)`，
    其中 `_SUBPROCESS_TIMEOUT_SECONDS` 为模块常量，默认 `600`（单图最坏含 4 次指数退避重试，
    需留足余量）。
  - 非零返回码 / `TimeoutExpired` → 记 `returncode` 与 `stderr` 尾部到日志，**不抛**。

### 2. 改 `backend/app/api/routes/analyses.py`

在 `confirm_analyses` 的循环里收集 `inaccurate_image_ids`（`not item.accurate` 的 `image_id`）。
在 `set_conversation_confirmed` 之后追加：

```python
if settings.annotation_pipeline_enabled and inaccurate_image_ids:
    background_tasks.add_task(
        annotation_pipeline_bridge.run_for_images,
        settings.database_path, settings, inaccurate_image_ids,
    )
```

约 6 行。不改变端点的返回值与既有行为。

### 3. 改 `backend/app/core/config.py`

新增三个可选项（默认值见下，缺省即关闭）：

- `annotation_pipeline_enabled: bool = Field(False, alias="ANNOTATION_PIPELINE_ENABLED")`
- `annotation_pipeline_rule_blocks: str = Field("知识图谱主文件/four_openings_edges_rule_blocks.json", alias="ANNOTATION_PIPELINE_RULE_BLOCKS")`
- `annotation_pipeline_output_dir: str = Field("runtime/annotation_pipeline_outputs", alias="ANNOTATION_PIPELINE_OUTPUT_DIR")`

### 4. 改 `.env.example` 与 `README.md`

`.env.example` 增加上述三项（注释说明默认关）。`README.md` 增一节：开关说明、自动触发的草标
产物位置、以及人工复核/提交命令（`--serve-review` / `--commit-reviewed --append-to-db`）。

### 5. 新增 `backend/tests/test_annotation_pipeline_bridge.py`

全程 mock，无网络、无真实子进程（`monkeypatch` `subprocess.run`）。

## 配置与优雅降级

- **总开关默认关**：`ANNOTATION_PIPELINE_ENABLED` 未开 → confirm 行为与现状完全一致。
- **规则文件**：默认指向已存在的 `知识图谱主文件/four_openings_edges_rule_blocks.json`；
  缺失时桥接记日志跳过，不报错——与 `regulation_search`/`report_scheduler` 为 None 时一致。
- **api_config 自动生成**：由 `.env` 派生，用户无需手填；母数据库目录在人工提交时自建。

## 错误处理

confirm 端点**永不因流水线失败而失败**：它先完成 annotation.db 写入并返回成功，流水线触发是
fire-and-forget 后台任务（与偏好更新同款）。子进程非零退出/超时仅记日志。

## 安全与隔离

- `runtime/annotation_pipeline/api_config.json` 含 API key：落在 `runtime/`（已 gitignore），
  权限 `0o600`，与 `.env` 同一信任边界（同机本地文件）。
- 用户隔离：触发仅针对 confirm 请求里当前用户自己对话的图片（`get_image_by_id` 由 confirm 端点
  已校验对话归属后取得）；草标产物不含用户标识，按 `sample_id` 组织。

## 测试与验证

单元测试（mock）：
1. 开关关闭 → confirm 不调度后台任务（route 层 patch `run_for_images` 断言未调用）。
2. 开启但规则文件缺失 → `run_for_images` 记日志并 return，`subprocess.run` 未被调用。
3. 开启 + 规则文件存在（tmp）+ 2 张不准确图 → `subprocess.run` 被调 2 次且参数符合预期；
   准确图不在内。
4. `ensure_api_config` 写出的 JSON 含正确 endpoint/key/model。
5. 子进程返回非零 → `run_for_images` 不抛异常。

端到端验证：
- `pytest` 全绿（新测试通过；旧 154 项因默认关而不受影响）。
- 冒烟：设 `ANNOTATION_PIPELINE_ENABLED=true`，对一张图 `POST /api/analyses/confirm`
  （`accurate=false`），确认 `runtime/annotation_pipeline_outputs/` 生成 `draft_json/` 等产物。
  （可先用流水线自带 `--mock-from-json` 验证子进程接线，无需网络。）
- 人工链路：`--serve-review` 浏览器复核 → `--commit-reviewed --append-to-db` 产出训练 JSONL。

## 已知限制与假设

- **模型能力**：复用 `VLM_MODEL` 意味着它需按流水线格式输出边界框；当前若为通用模型，草标质量
  一般——由人工复核兜底，后续微调模型逐步改善（符合用户"用同一套 API"的决定）。
- `draft_summary.json` 在单图运行时会被覆盖为仅本图统计（cosmetic）；人工复核工具扫描的是
  `review_decisions/*.review.json`，累积正常。
- `stable_sample_id` 对非 `foe_NNNNNN` 文件名用路径 crc32（百万取模），存在极小碰撞概率。
- 无 Pillow 时 `image_dimensions` 仅支持 png/jpg（webp 会报错）；建议环境装 Pillow。
- `--source-type` 仅在人工提交阶段使用（默认 `generated_seed`）；上传图为真实现场照，复核提交时
  应由人工传 `--source-type real_site`。草标阶段不涉及该参数。

## 范围外（本设计不做）

- 不改动 `annotation_pipeline/` 内任何代码。
- 不加对话 LLM tool 入口（用户选 A：仅按钮）。
- 不改人工复核/提交流程与前端。
- 不做攒批/队列/定时（用户选"每张即时后台跑"）。

# Agent 内置数据标注流水线说明

这个目录保存从“四口五临边”研究项目复制进来的 API 辅助标注流水线。复制到 `safety-vision-agent` 后，仓库可以自包含地完成后续批量草标、人工复核和 `accepted_records` 生成，不依赖外部研究目录。

Agent 当前已经优先接入“从一次分析结果进入标注复核”的单样本闭环；本目录保留的是更完整的批量标注流水线能力。

## 模块职责

| 文件 | 职责 |
|---|---|
| `cli.py` | 命令行参数、入口分发：草标流程或 review 提交流程 |
| `runner.py` | 扫描图片、调用单图处理、并发调度、写 summary |
| `api_client.py` | 调用多模态 API、解析模型响应文本和 JSON |
| `prompt.py` | 构造四口五临边识别 prompt |
| `rules.py` | 加载知识图谱规则块，按对象/状态匹配规则文本 |
| `normalize.py` | 规范化 API 草稿对象、bbox、状态、证据和规则 |
| `review_render.py` | 生成带 bbox 的复核图，优先 PNG，缺少 Pillow 时回退 SVG |
| `review_index.py` | 旧版只读 HTML 复核页；只有加 `--write-review-index` 时生成 |
| `review_records.py` | 将人工 accept/revise 的 review JSON 转成 `accepted_records`，可追加到母数据库 |
| `summary.py` | 统计草标结果分布和 warning |
| `image_utils.py` | 图片扫描、尺寸读取、base64 data URL、稳定 sample_id |
| `io_utils.py` | JSON/JSONL 读写、配置加载、endpoint 转换 |
| `constants.py` | schema version、对象类型、隐患类型、状态相关常量 |
| `local_deps.py` | 加载根目录 `.python_deps`，用于本地 Pillow |

## 常用命令

从 `backend` 目录运行批量草标：

```bash
python -m app.annotation_pipeline.cli \
  --image-dir ../uploads \
  --rule-blocks ../configs/rules/four_openings_edges_rule_blocks.example.json \
  --output-dir ../outputs/annotation_pipeline \
  --limit 10 \
  --mock-from-json
```

真实 API 模式需要准备配置文件，建议放在不提交的本地路径中：

```bash
python -m app.annotation_pipeline.cli \
  --config ../configs/annotation_api_config.json \
  --image-dir ../uploads \
  --rule-blocks ../configs/rules/four_openings_edges_rule_blocks.example.json \
  --output-dir ../outputs/annotation_pipeline \
  --limit 10
```

人工复核完成后，把 `review_decisions/*.review.json` 中对象的 `decision` 改为 `accept`、`reject` 或 `revise`，再执行：

```bash
python -m app.annotation_pipeline.cli \
  --commit-reviewed \
  --output-dir ../outputs/annotation_pipeline \
  --db-records-dir ../outputs/annotation_db/records
```

如确认要直接追加到母数据库，再加：

```bash
--append-to-db
```

## 浏览器审核工具

可以启动本地审核页面，直接在浏览器里修改 review JSON：

```bash
python -m app.annotation_pipeline.cli \
  --serve-review \
  --output-dir ../outputs/annotation_pipeline \
  --db-records-dir ../outputs/annotation_db/records \
  --review-port 8765
```

打开：

```text
http://127.0.0.1:8765
```

页面能力：

- 左侧选择样本。
- 中间查看原图和草标框图。
- 右侧直接编辑对应的 `review_decisions/*.review.json`。
- `保存 JSON` 会写回当前 review JSON。
- `待定改通过` 会把当前样本里的 pending 对象改为 accept。
- `生成 accepted_records` 会调用 review 转换逻辑，只写 `accepted_records/`。
- `导入母数据库` 会先生成 accepted_records，再追加到 `annotation_db/records/`。

## 输出关系

草标流程会写入：

```text
../outputs/annotation_pipeline/
  raw_response/       API 原始响应或 mock 来源记录
  draft_json/         规范化 API 草稿
  boxed_review/       带框复核图
  review_decisions/   人工编辑的 review JSON
  draft_summary.json  本轮统计
```

默认不再生成 `review_index/`；人工审核推荐使用 `--serve-review` 浏览器审核工具。需要旧版只读 HTML 时，草标命令加 `--write-review-index`。

提交 review 后会写入：

```text
../outputs/annotation_pipeline/accepted_records/
  images.jsonl
  objects.jsonl
  commit_summary.json
```

## 维护建议

- 改旧版静态复核页，优先改 `review_index.py`。
- 改浏览器审核工具，优先改 `review_server.py`。
- 改框图颜色、标签或图片输出格式，优先改 `review_render.py`。
- 改 API 接口适配，优先改 `api_client.py`。
- 改模型输出字段或校验规则，优先改 `normalize.py` 和 `review_records.py`。
- 模型不输出 `rule_id` 和 `rule`；程序在 `rules.py` 中根据 `object_id/status/hazard_type_id/visual_evidence` 自动匹配规则。
- `../configs/annotation_api_config.json` 不建议提交真实 API key；本仓库 `.gitignore` 已忽略 `api_config.json`，真实密钥仍应放在本地或环境变量中。

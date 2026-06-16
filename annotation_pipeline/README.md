# 数据处理流水线代码说明

这个目录保存“四口五临边”API 辅助标注流水线的拆分代码。根目录的 `api_annotation_pipeline.py` 仍然是兼容入口，实际实现已经迁移到本目录。

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

从 `数据标注` 的上一级目录运行时，可以继续使用旧命令：

```bash
python 数据标注/api_annotation_pipeline.py --image-dir 数据标注/生成图片 --limit 10 --mock-from-json
```

如果当前工作目录已经是 `数据标注`，需要显式传相对路径：

```bash
python api_annotation_pipeline.py \
  --mock-from-json \
  --image-dir 生成图片 \
  --rule-blocks 知识图谱主文件/four_openings_edges_rule_blocks.json \
  --output-dir annotation_pipeline_outputs \
  --limit 2 \
  --overwrite
```

人工复核完成后，把 `review_decisions/*.review.json` 中对象的 `decision` 改为 `accept`、`reject` 或 `revise`，再执行：

```bash
python api_annotation_pipeline.py \
  --commit-reviewed \
  --output-dir annotation_pipeline_outputs \
  --db-records-dir annotation_db/records
```

如确认要直接追加到母数据库，再加：

```bash
--append-to-db
```

## 浏览器审核工具

可以启动本地审核页面，在浏览器里完成框、对象类型、隐患类型和审核结论修改：

```bash
python api_annotation_pipeline.py \
  --serve-review \
  --output-dir annotation_pipeline_outputs \
  --db-records-dir annotation_db/records \
  --review-port 8765
```

打开：

```text
http://127.0.0.1:8765
```

页面能力：

- 左侧选择样本。
- 中间查看原图，页面会根据当前 review JSON 的 `bbox` 实时叠加框。
- 点选框可以切换对象；拖动框可以移动；拖动角点可以缩放；bbox 数字会同步更新。
- 没有框或漏框时，可以点 `新增对象`，也可以直接在图上拖出新框。
- 右侧表单可以修改对象类型、审核结论、状态、隐患类型、bbox、证据、规则和审核备注。
- `通过` 表示该对象可入库；`误报/删除` 表示该对象不入库；`待定` 表示暂不入库。
- `高级 JSON` 只用于必要时排查或精细修改，非技术审核人员通常不用打开。
- `保存 JSON` 会写回当前 review JSON。
- `标为需重跑` / `取消重跑` 会给当前样本写入 `needs_rerun`，用于后续只重跑坏样本。
- `待定改通过` 会把当前样本里的 pending 对象改为 accept。
- `生成 accepted_records` 会调用 review 转换逻辑，只写 `accepted_records/`。
- `导入母数据库` 会先生成 accepted_records，再追加到 `annotation_db/records/`。

只重跑页面里标记为 `needs_rerun` 的样本：

```bash
python api_annotation_pipeline.py \
  --image-dir images \
  --config api_config.json \
  --rule-blocks 知识图谱主文件/four_openings_edges_rule_blocks.json \
  --output-dir annotation_pipeline_outputs \
  --only-needs-rerun \
  --workers 4 \
  --timeout 240
```

`--only-needs-rerun` 会自动开启覆盖模式，只覆盖被标记样本对应的 `raw_response/`、`draft_json/`、`review_decisions/` 和框图。

## 当前 prompt 策略

模型只负责看图输出对象类别、bbox、状态、隐患类型和视觉证据，不根据文件名判断。对象类型和隐患类型列表从 `知识图谱主文件/four_openings_edges_rule_blocks.json` 读取，当前为 9 类对象、9 类隐患。

## 输出关系

草标流程会写入：

```text
annotation_pipeline_outputs/
  raw_response/       API 原始响应或 mock 来源记录
  draft_json/         规范化 API 草稿
  boxed_review/       带框复核图
  review_decisions/   浏览器审核工具保存的 review JSON
  draft_summary.json  本轮统计
```

默认不再生成 `review_index/`；人工审核推荐使用 `--serve-review` 浏览器审核工具。需要旧版只读 HTML 时，草标命令加 `--write-review-index`。

提交 review 后会写入：

```text
annotation_pipeline_outputs/accepted_records/
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
- `api_config.json` 不建议长期保存明文 API key，后续可以改为读取环境变量。

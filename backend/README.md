# 四口五临边隐患问答助手（后端）

围绕本地 vLLM 微调视觉模型 + 知识图谱 + 标准向量 RAG 的交互式安全隐患问答助手（后端 API）。

## 安装
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env   # 按需填写;VLM_API_BASE_URL 指向本地 vLLM
```

## 构建标准向量库（RAG）
首次运行前，对 JGJ 标准 OCR 文档建立向量索引：
```bash
cd backend && python scripts/build_standards_index.py
```

## 运行
```bash
cd backend && uvicorn app.main:app --reload --port 8000
```

## 主要接口
- `POST /sessions` → `{session_id}`
- `POST /sessions/{id}/images`（multipart 字段 `file`）→ 触发识别，返回隐患列表 + 主动确认问句
- `POST /sessions/{id}/messages` `{ "text": "..." }` → 多轮问答 / 确认 / 纠错
- `GET /sessions/{id}/report/download` → 下载 Word（.docx）报告（需先通过对话触发 `export_report` 工具生成）
- `GET /sessions/{id}` → 会话消息；`GET /health`

## 纠错数据流（人在回路）
识别后助手主动询问"是否正确"。用户指出有误并说明后，助手调用 `submit_correction`，把
`{图片 + VLM 草稿(--mock-from-json 配套 JSON) + 纠错备注}` 写入 `PIPELINE_INTAKE_DIR`（默认 `runtime/pipeline_intake`）。
后端不运行流水线、不写母库。数据团队事后：
```bash
python api_annotation_pipeline.py --mock-from-json \
  --image-dir runtime/pipeline_intake/images \
  --rule-blocks 知识图谱主文件/four_openings_edges_rule_blocks.json \
  --output-dir annotation_pipeline_outputs
python api_annotation_pipeline.py --serve-review --output-dir annotation_pipeline_outputs
```
浏览器复核（accept/revise）后 `--commit-reviewed --append-to-db` 入母库。

## 配置（.env）
复用共享 OpenAI 兼容配置 `OPENAI_API_BASE_URL`/`OPENAI_API_KEY`/`AGENT_MODEL`/`EMBEDDING_MODEL`，
VLM 独立可选 `VLM_MODEL`/`VLM_API_BASE_URL`/`VLM_API_KEY`（未设时回退共享配置），
运行目录 `CHROMA_DIR`/`UPLOAD_DIR`/`REPORT_DIR`/`DATABASE_PATH`/`PIPELINE_INTAKE_DIR`，
以及 `MAX_IMAGE_BYTES`/`MAX_TOOL_ITERATIONS`。

## 测试
```bash
cd backend && python -m pytest -q
```

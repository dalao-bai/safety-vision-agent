# safety-vision-agent

多轮对话式施工安全隐患识别专家 Agent。

本项目用于构建一个基于微调 VLM API、YOLO 检测 API、规则检索、记忆管理和报告生成的施工现场安全隐患识别系统。第一版采用按需推理方案：用户上传图片或指定历史图片后，Agent 根据多轮对话意图调用相关视觉工具，并融合证据生成结构化判断和检查报告。

## 核心能力

- 多轮对话式隐患识别。
- 调用微调 VLM API 识别四口五临边隐患。
- 调用 YOLO API 检测人员、安全帽和未佩戴安全帽人员。
- 基于规则块进行四口五临边规则检索。
- 融合 VLM、YOLO、规则和历史上下文。
- 输出结构化 JSON、带框图片和检查报告。
- 保存会话、图片、工具调用日志和分析结果。
- 支持人工复核后的标注反哺闭环，将需修正结果生成训练候选数据。
- 内置四口五临边 API 辅助标注流水线代码，支持后续批量草标和审核台扩展。

## 当前边界

本仓库第一版不做 VLM 后台实时视频逐帧巡检。VLM 和 YOLO 都作为外部 API 工具按需调用。Agent 项目不保存模型权重。

标注流水线只用于人工复核、数据沉淀和后续训练数据构造，不会阻塞正常隐患推理流程。

## 推荐目录

```text
safety-vision-agent/
├── backend/          FastAPI 后端和 Agent 工具
│   └── app/annotation_pipeline/  四口五临边数据标注流水线副本
├── frontend/         Next.js 前端原型
├── configs/          配置模板和规则示例
├── docs/             规划、架构、API 契约和路线图
├── scripts/          本地辅助脚本
├── .env.example      环境变量占位，真实值不要提交
└── .gitignore
```

## 快速开始

后端：

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env
uvicorn app.main:app --reload
```

前端：

```bash
cd frontend
npm install
npm run dev
```

## 必填配置

真实 API 地址、密钥和规则文件路径都在 `.env` 中填写。仓库只提交 `.env.example`。

```text
LLM_API_BASE_URL=
LLM_API_KEY=
VLM_API_BASE_URL=
VLM_API_KEY=
YOLO_API_BASE_URL=
YOLO_API_KEY=
RULE_BLOCKS_PATH=
```

## 标注反哺闭环

当前支持从一次分析结果进入标注复核：

```text
分析结果
-> 前端点击“进入标注复核”
-> 后端创建 annotation sample
-> 人工 accept / revise / reject
-> 生成 accepted_records
-> 写入 training_candidates
```

生成的训练候选记录会保存到数据库，同时在后端运行目录写入：

```text
outputs/annotation_feedback/{sample_id}/
  accepted_records.json
  images.jsonl
  objects.jsonl
```

## GitHub 提交建议

建议使用 private 私有仓库，不要提交真实密钥、真实数据、上传图片、视频或数据库文件。

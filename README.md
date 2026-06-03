# safety-vision-agent

多轮对话式施工安全隐患识别专家 Agent。

本项目用于构建一个基于微调 VLM API、YOLO 检测、规则检索、记忆管理和报告生成的施工现场安全隐患识别系统。第一版采用按需推理方案：用户上传图片或指定历史图片后，Agent 根据多轮对话意图调用相关视觉工具，并融合证据生成结构化判断和检查报告。

## 核心能力

- 多轮对话式隐患识别。
- 调用微调 VLM API 识别四口五临边隐患。
- 调用 YOLO 检测人员、安全帽和未佩戴安全帽人员。
- 基于规则块进行四口五临边规则检索。
- 融合 VLM、YOLO、规则和历史上下文。
- 输出结构化 JSON、带框图片和检查报告。
- 保存会话、图片、工具调用日志和分析结果。

## 当前边界

本仓库第一版不做 VLM 后台实时视频逐帧巡检。VLM 是按需调用的视觉专家工具。实时或准实时任务后续由 YOLO、tracking 和任务队列扩展。

## 推荐目录

```text
safety-vision-agent/
├── backend/          FastAPI 后端和 Agent 工具
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

真实 API 地址、密钥、YOLO 权重路径和规则文件路径都在 `.env` 中填写。仓库只提交 `.env.example`。

```text
LLM_API_BASE_URL=
LLM_API_KEY=
VLM_API_BASE_URL=
VLM_API_KEY=
YOLO_HELMET_MODEL_PATH=
RULE_BLOCKS_PATH=
```

## GitHub 提交建议

建议先创建 private 私有仓库：

```text
safety-vision-agent
```

不要提交真实密钥、真实数据、模型权重、上传图片、视频或数据库文件。

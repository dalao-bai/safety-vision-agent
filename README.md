# safety-vision-agent

多轮对话式施工安全隐患识别专家 Agent。

当前 MVP 主线是 `FastAPI + SQLite + Vite React`，后端使用轻量 Agent 状态机编排工具。系统支持上传施工现场图片后多轮追问：隐患识别、依据解释、整改建议、报告生成、人工复核和标注反哺。

## 核心能力

- 多轮对话：同一 `conversation_id` 下复用会话历史、图片历史和最新融合结果。
- Agent 路由：按用户意图决定从记忆回答，还是调用 VLM、YOLO、规则、整改、报告工具。
- 视觉工具：微调 VLM API 识别四口五临边隐患，YOLO API 检测人员/安全帽。
- 规则和证据融合：本地规则块检索，融合 VLM、YOLO、规则和不确定项。
- SQLite 业务记忆：保存会话、消息、上传文件、工具调用、分析结果、复核、整改、标注样本和训练候选。
- 轻量前端：Vite React 控制台用于上传图片、发起多轮对话、查看结构化结果和验证闭环。

## 目录

```text
backend/          FastAPI、Agent 状态机、SQLite repository、工具服务
frontend/         Vite React Agent 控制台
configs/          规则示例
docs/             架构、API、路线图和计划
scripts/          本地辅助说明
runtime/          本地上传、输出和 SQLite 数据库，默认不提交
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

默认前端地址是 `http://127.0.0.1:5173`，后端地址是 `http://127.0.0.1:8000`。

## 配置

`.env.example` 中保留 MVP 所需配置：

```text
SQLITE_PATH=runtime/safety_vision_agent.sqlite3
VLM_API_BASE_URL=
VLM_API_KEY=
VLM_MODEL_NAME=
YOLO_API_BASE_URL=
YOLO_API_KEY=
RULE_BLOCKS_PATH=configs/rules/four_openings_edges_rule_blocks.example.json
```

未配置 VLM/YOLO 时，后端会返回可运行的降级结果，便于本地验证 Agent、多轮记忆和前端闭环。

## 已移出 MVP 主线

SQLAlchemy、Alembic、Celery、Redis、PostgreSQL/psycopg、pydantic-settings、LangGraph checkpoint 和 Next.js 已移出当前运行路径。队列、高并发、PostgreSQL 迁移、向量检索和更完整产品 UI 都作为后续扩展处理。

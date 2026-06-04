# 实现状态

## 已接入

- FastAPI + SQLite + 轻量 Agent 状态机 MVP 主线。
- SQLite schema 和 repository，启动时自动初始化应用业务表。
- Agent 多轮入口 `/api/chat`，返回 answer、conversation_id、latest_analysis_id、fused_result、tool_calls、artifacts、errors。
- 会话记忆、图片历史、最新融合结果和“第 N 个隐患”追问解析。
- VLM、YOLO、规则检索、证据融合工具包装，并记录工具调用日志。
- VLM/YOLO 未配置时的本地降级响应。
- inline 分析流程，兼容 `/api/analysis` 和 `/api/analysis/{analysis_id}`，不再依赖任务队列。
- 图片上传、类型/大小限制和 file_id 路径安全校验。
- 人工复核、整改任务、标注反哺和训练候选数据生成。
- Vite React Agent 控制台：上传、聊天、结构化结果、整改和标注样本入口。
- `annotation_pipeline` 四口五临边 API 辅助标注流水线代码。

## 仍需人工配置

- `VLM_API_BASE_URL`
- `VLM_API_KEY`
- `VLM_MODEL_NAME`
- `YOLO_API_BASE_URL`
- `YOLO_API_KEY`
- `LLM_API_BASE_URL`
- `LLM_API_KEY`
- `SQLITE_PATH`
- 批量标注流水线如直接调用 CLI，还需要配置 `../configs/annotation_api_config.json` 或显式传入 `--config`。

## 已移出当前 MVP

- SQLAlchemy / Alembic。
- Redis / Celery worker。
- PostgreSQL / psycopg 兼容。
- pydantic-settings。
- LangGraph checkpoint。
- Next.js。

## 启动提示

后端：

```bash
cd backend
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

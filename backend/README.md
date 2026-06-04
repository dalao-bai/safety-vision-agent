# Backend

FastAPI 后端，负责文件上传、LangGraph Agent 编排、工具调用和 SQLite 业务记忆。

## 启动

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env
uvicorn app.main:app --reload
```

启动时会创建运行目录并执行 `backend/app/db/schema.sql` 初始化 SQLite 表。当前 MVP 不需要 Redis、Celery worker、Alembic 或 PostgreSQL。

## 主要入口

- `POST /api/files/images`：上传图片。
- `POST /api/chat`：Agent 多轮主入口，支持 `conversation_id`、`file_id`、`message`。
- `GET /api/analysis/{analysis_id}`：兼容查询最新融合结果。
- `POST /api/remediations`：创建整改任务。
- `POST /api/annotations/from-analysis`：从分析结果创建标注复核样本。

VLM、YOLO、LLM API 均通过 `.env` 配置。未配置 VLM/YOLO 时，服务会返回降级结果，便于本地跑通流程。

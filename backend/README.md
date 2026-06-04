# Backend

FastAPI 后端，负责文件上传、ReAct Agent 编排、工具调用和 SQLite 业务记忆。

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
- `POST /api/chat`：Agent 多轮主入口，支持 `conversation_id`、`message`、`file_id/file_ids`、`image_path/image_paths`。
- `GET /api/analysis/{analysis_id}`：兼容查询最新融合结果。
- `POST /api/remediations`：创建整改任务。
- `POST /api/annotations/from-analysis`：从分析结果创建标注复核样本。

## Agent 结构

当前 Agent 主路径在 `backend/app/agent/`：

- `planner.py`：根据用户目标和已有观察选择下一步 approved action。
- `executor.py`：执行有最大步数限制的 ReAct 循环，并持久化 `react_*` 工具轨迹。
- `tools.py`：封装图片分析、多图合并、记忆读取、规则依据、风险评分、整改任务和报告生成。
- `formatter.py`：把结构化结果格式化为中文回答。
- `graph.py`：保留 `run_safety_agent` 兼容入口，内部转到 ReAct executor。

旧的 `router.py` / `nodes.py` 固定关键词路由已删除。当前默认使用 deterministic ReAct fallback，便于本地测试；真实 LLM planner 可后续在同一结构上接入。

VLM、YOLO、LLM API 均通过 `.env` 配置。未配置 VLM/YOLO 时，服务会返回降级结果，便于本地跑通流程。

# 实现状态

## 已接入

- PostgreSQL/SQLite 数据模型。
- Alembic 初始迁移和开发环境启动迁移。
- Redis/Celery 配置。
- Celery 图片分析任务。
- 分析任务创建、状态查询、结果查询接口。
- 图片上传入库，并限制图片类型和大小。
- 前端上传、创建分析任务、轮询任务状态、展示结果。
- `uncertain` 主动追问和补拍建议。
- 人工复核 API，并校验 analysis 和 item index。
- 隐患整改任务 API，并校验分析结果和整改任务存在性。
- 前端确认、需修正、生成整改任务入口。
- VLM、YOLO、规则检索、证据融合工具调用日志落库。
- YOLO 只通过外部 API 调用，本项目不保存或加载 YOLO 权重。

## 仍需人工配置

- `VLM_API_BASE_URL`
- `VLM_API_KEY`
- `VLM_MODEL_NAME`
- `YOLO_API_BASE_URL`
- `YOLO_API_KEY`
- `LLM_API_BASE_URL`
- `LLM_API_KEY`
- `DATABASE_URL`
- `REDIS_URL`

## 启动提示

后端：

```bash
cd backend
pip install -r requirements.txt
cp ../.env.example .env
uvicorn app.main:app --reload
```

Celery worker：

```bash
cd backend
celery -A app.tasks.celery_app.celery_app worker --loglevel=info
```

前端：

```bash
cd frontend
npm install
npm run dev
```

# 实现状态

## 已接入

- PostgreSQL/SQLite 数据模型。
- Alembic 初始迁移。
- Redis/Celery 配置。
- Celery 图片分析任务。
- 分析任务创建、状态查询、结果查询接口。
- 图片上传入库。
- 前端上传、创建分析任务、轮询任务状态、展示结果。

## 仍需人工配置

- `VLM_API_BASE_URL`
- `VLM_API_KEY`
- `VLM_MODEL_NAME`
- `LLM_API_BASE_URL`
- `LLM_API_KEY`
- `YOLO_HELMET_MODEL_PATH`
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

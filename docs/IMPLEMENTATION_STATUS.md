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
- 标注反哺闭环 API：可从分析结果创建标注复核样本、保存人工复核、生成训练候选数据。
- 前端标注反哺入口：支持进入标注复核、编辑对象 JSON、保存复核、生成训练样本。
- 已复制 `annotation_pipeline` 到 `backend/app/annotation_pipeline/`，仓库自包含四口五临边 API 辅助标注流水线代码。
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
- 批量标注流水线如直接调用 CLI，还需要配置 `../configs/annotation_api_config.json` 或显式传入 `--config`。

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

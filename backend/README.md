# Backend

FastAPI 后端，负责文件上传、多轮对话、Agent 编排、工具调用和结果存储。

## 启动

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env
uvicorn app.main:app --reload
```

## 说明

当前 VLM API、LLM API 和 YOLO API 均为空配置，需要在 `.env` 中填写。

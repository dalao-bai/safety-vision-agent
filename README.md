# 工地安全隐患识别 Agent (v0.2)

Multi-user construction-site safety hazard detection system. Upload one or more photos, get structured hazard analysis with risk ranking and remediation advice, query a semantic regulation library, and generate compliance reports — all through a conversational agent interface.

This is **v0.2**: production-oriented multi-user backend. It is enterprise-internal software, **not a legal safety-compliance system** and not a replacement for professional safety inspection.

## Stack

| Layer | Technology |
| --- | --- |
| Backend | FastAPI + SQLite |
| Agent orchestration | LangGraph `create_react_agent` (LangChain v1 / LangGraph 1.2) |
| Image analysis | OpenAI-compatible VLM via Responses API |
| Semantic search | ChromaDB + embedding model |
| Auth | Username login + JWT |
| Report generation | python-docx |
| Frontend | React + Vite (TypeScript) |

## How It Works

```
React/Vite UI ──> FastAPI (JWT auth) ──> LangGraph Agent
                        │                      │
                        │         ┌────────────┼────────────────────┐
                        │         │            │                    │
                        │    analyze_image  search_regulations  generate_report
                        │    explain_basis  query_history
                        │    rank_risks
                        │    suggest_remediation
                        │
                        ├── SQLite (messages / analyses / tool calls / audit)
                        ├── ChromaDB (regulation embeddings)
                        ├── annotation.db (images flagged for re-labeling)
                        └── runtime/uploads/{user_id}/
```

1. User logs in with a username + API key; backend issues a JWT.
2. User uploads a construction-site photo with a message.
3. The LangGraph agent receives 7 tools (bound via closure to the current user's context).
4. `analyze_image` sends the image to the VLM and persists structured hazard JSON.
5. Follow-up questions reuse the saved analysis (`explain_basis`, `rank_risks`, `suggest_remediation`).
6. `search_regulations` does semantic retrieval over uploaded PDF/Word regulation files.
7. `generate_report` triggers an async background task that produces a `.docx` compliance report.
8. `query_history` aggregates the user's hazard statistics across past conversations.
9. Every model call and tool invocation is persisted for audit.

### Three-layer memory

| Layer | Scope | Mechanism |
| --- | --- | --- |
| In-conversation | Current conversation | Sliding window (last 20 messages, first message kept) |
| User preferences | Cross-conversation | LLM-generated preference summary injected as system context |
| Hazard statistics | Cross-conversation | Aggregated `user_hazard_stats` table, updated on analysis confirmation |

### Analysis confirmation flow

After all images are analyzed, the frontend shows a per-image checklist. The user confirms accuracy via `POST /api/analyses/confirm`:
- All accurate → triggers async preference update
- Any inaccurate → those images are written to `annotation.db` for relabeling

## Configuration

Copy `.env.example` to `.env` and fill in:

| Variable | Required | Description |
| --- | --- | --- |
| `OPENAI_API_BASE_URL` | yes | OpenAI-compatible API base URL |
| `OPENAI_API_KEY` | yes | API key |
| `VLM_MODEL` | yes | Model for image analysis (must accept image input) |
| `AGENT_MODEL` | yes | Model for tool selection and final answers (must support function calling) |
| `JWT_SECRET` | yes | Secret for signing JWTs — use a long random string |
| `JWT_ALGORITHM` | no | JWT algorithm (default `HS256`) |
| `JWT_EXPIRE_MINUTES` | no | Token lifetime in minutes (default `1440`) |
| `EMBEDDING_MODEL` | no | Embedding model for regulation search (default `text-embedding-3-small`) |
| `CHROMA_DIR` | no | ChromaDB persistence directory (default `runtime/chroma`) |
| `REGULATION_DIR` | no | Uploaded regulation files directory (default `runtime/regulations`) |
| `MAX_REGULATION_BYTES` | no | Max regulation file size (default 20 MiB) |
| `DATABASE_PATH` | no | Main SQLite file (default `runtime/agent.db`) |
| `ANNOTATION_DB_PATH` | no | Annotation SQLite file (default `runtime/annotation.db`) |
| `UPLOAD_DIR` | no | Uploaded image directory (default `runtime/uploads`) |
| `REPORT_DIR` | no | Generated report output directory (default `runtime/reports`) |
| `MAX_IMAGE_BYTES` | no | Max image upload size (default 10 MiB) |
| `MAX_TOOL_ITERATIONS` | no | Agent tool-loop cap (default `5`) |

Missing or invalid required values fail at startup with a clear message.

## Local Setup

### Backend

```bash
cd backend
pip install -r requirements.txt
pytest                        # 154 tests, no network needed — model calls are mocked
uvicorn app.main:app --reload  # http://127.0.0.1:8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev   # http://localhost:5173 (proxies /api to the backend)
npm test
```

Run both, open http://localhost:5173, log in, upload an image, and ask "请识别这张图的安全隐患". Follow-ups: "判断依据是什么?", "哪个隐患最严重?", "应该怎么整改?", "有哪些规范要求?", "生成本月报告".

## API Overview

```
POST   /api/auth/login                  { username, api_key } → { token, user_id }

POST   /api/chat                        multipart — main conversation endpoint
POST   /api/analyses/confirm            { conversation_id, image_confirmations }

GET    /api/regulations                 list uploaded regulation files
POST   /api/regulations/upload          upload PDF or Word regulation file
DELETE /api/regulations/{id}            soft-delete a regulation file

GET    /api/history                     ?start=&end= — hazard history for current user
GET    /api/annotation/export           CSV export of images flagged for relabeling

POST   /api/report/generate             { start_date, end_date } → { task_id }
GET    /api/report/status/{task_id}     poll report generation status + download URL
```

## Project Structure

```
backend/
  app/
    agent/          LangGraph orchestrator, context assembly, tools (7), prompts, audit callback
    api/            FastAPI routes, dependency injection, JWT auth
    core/           configuration
    db/             SQLite schema, connection, repositories, annotation.db layer
    models/         Pydantic domain schemas
    services/       image storage, VLM analyzer, regulation store (ChromaDB),
                    report generator (docx), preference updater, security utils
  tests/            154 backend tests
frontend/
  src/              React app, API helper, shared types
runtime/            uploads, databases, chroma, reports (git-ignored)
docs/               requirements, plans, design documents
```

## Data Handling

- **User isolation**: all queries are scoped to `user_id` from the JWT. Conversations, images, analyses, and history are per-user. Regulation files are global (shared).
- **Local storage**: SQLite stores conversations, messages, image metadata, structured hazard analysis, every tool call with timing, and raw model responses. Images are stored under `runtime/uploads/{user_id}/`.
- **Annotation data**: images flagged as incorrectly analyzed are written to `runtime/annotation.db` for later re-labeling and model improvement.
- **No external data transmission** beyond the configured model API endpoint.

## Status

v0.2 complete (154 tests passing). Agent orchestration runs on LangGraph `create_react_agent`. See `docs/` for implementation plans and design documents.

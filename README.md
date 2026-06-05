# 工地安全隐患识别 Agent (v0.1)

A local single-user MVP that identifies construction-site safety hazards from an uploaded image using a real VLM, then answers follow-up questions (basis, risk ranking, remediation) via model-driven tool calling.

This is **v0.1**: the smallest useful end-to-end Agent loop. It is local-only software, **not a production safety-compliance system** and not a replacement for professional safety inspection.

## Stack

- Backend: FastAPI + SQLite, OpenAI-compatible Responses API
- Frontend: React + Vite (TypeScript)

## How It Works

1. You upload one construction-site image and ask a question.
2. The backend stores the image, creates a conversation, and calls the **Agent model** with four tools.
3. The Agent model calls `analyze_image`, which sends the image to the **VLM model** and forces structured hazard JSON (validated server-side).
4. Follow-up questions reuse the saved analysis through `explain_basis`, `rank_risks`, and `suggest_remediation` — no re-analysis needed.

```
React/Vite UI ──> FastAPI ──> Agent orchestrator ──> Agent model (tool calling)
                     │                  │
                     │                  ├─ analyze_image ──> VLM model ──> structured JSON
                     │                  ├─ explain_basis / rank_risks / suggest_remediation
                     │                  │   (deterministic transforms over saved analysis)
                     ▼                  ▼
              SQLite (full local audit) + runtime/uploads/
```

## Configuration

Copy `.env.example` to `.env` and fill in:

| Variable | Required | Description |
| --- | --- | --- |
| `OPENAI_API_BASE_URL` | yes | OpenAI-compatible Responses API base URL |
| `OPENAI_API_KEY` | yes | API key |
| `VLM_MODEL` | yes | Model used for image hazard analysis (must accept image input) |
| `AGENT_MODEL` | yes | Model used for tool selection and final answers (must support function calling) |
| `DATABASE_PATH` | no | SQLite file path (default `runtime/agent.db`) |
| `UPLOAD_DIR` | no | Uploaded image directory (default `runtime/uploads`) |
| `MAX_IMAGE_BYTES` | no | Max upload size (default 10 MiB) |
| `MAX_TOOL_ITERATIONS` | no | Agent tool-loop cap (default 5) |

Missing or invalid required values fail at startup with a clear message.

## Local Setup

### Backend

```bash
cd backend
pip install -r requirements.txt
pytest                                   # run tests (no network needed; model calls are mocked)
uvicorn app.main:app --reload            # serves on http://127.0.0.1:8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev                              # http://localhost:5173 (proxies /api to the backend)
npm test                                 # run tests
```

Run both, open http://localhost:5173, upload an image, and ask "请识别这张图的安全隐患". Then try follow-ups: "判断依据是什么?", "哪个隐患最严重?", "应该怎么整改?".

## Project Structure

```
backend/
  app/
    agent/        orchestrator (tool-calling loop), context assembly, tools, prompts
    api/          FastAPI routes + dependency injection
    core/         configuration
    db/           SQLite schema, connection, repositories
    models/       Pydantic domain schemas
    services/     image storage, Responses API client, VLM analyzer
  tests/          backend test suite
frontend/
  src/            React app, API helper, shared types
runtime/          local image uploads + SQLite DB (git-ignored)
docs/             requirements, plans, roadmap
```

## Limitations & Data Handling (v0.1)

- **Local single-user only.** No authentication, no user isolation, no multi-tenancy.
- **Full local audit memory.** SQLite stores conversations, messages, image metadata, structured analysis, every tool call, and raw VLM/Agent responses (including errors) for debugging. Uploaded images are kept on disk under `runtime/`.
- No retention, redaction, or privacy controls yet — do not point this at real user data or deploy it. These are deferred to a later production-oriented version (see `docs/roadmap.md`).
- The Agent reports hazards based only on visible image evidence and does not claim legal/regulatory compliance.

## Status & Roadmap

v0.1 complete. See `docs/plans/2026-06-05-001-feat-v01-agent-mvp-plan.md` for the implementation plan and `docs/roadmap.md` for later versions (multi-image, rule references, reports, human review, remediation tracking, evaluation).

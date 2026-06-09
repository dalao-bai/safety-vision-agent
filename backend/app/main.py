"""FastAPI application entry point for the v0.1 Agent backend.

Constructs the app, validates configuration at startup, enables CORS for the
local frontend, and registers the chat router.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.analyses import router as analyses_router
from app.api.routes.annotation import router as annotation_router
from app.api.routes.auth import router as auth_router
from app.api.routes.chat import router as chat_router
from app.api.routes.history import router as history_router
from app.api.routes.regulations import router as regulations_router
from app.api.routes.report import router as report_router
from app.core.config import get_settings


def create_app() -> FastAPI:
    """Application factory. Validates configuration eagerly so misconfiguration
    fails at startup rather than on the first request."""
    app = FastAPI(title="Construction Safety Agent", version="0.2.0")

    # Local single-user dev: allow the Vite dev server origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # v0.1 对话端点 + v0.2 业务端点。
    app.include_router(chat_router)
    app.include_router(auth_router)
    app.include_router(analyses_router)
    app.include_router(regulations_router)
    app.include_router(history_router)
    app.include_router(annotation_router)
    app.include_router(report_router)

    # Touch settings so missing/invalid configuration surfaces at startup.
    get_settings()

    return app


app = create_app()

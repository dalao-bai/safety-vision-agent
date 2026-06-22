from __future__ import annotations

from fastapi import FastAPI

from app.api import images, messages, reports, sessions


def create_app() -> FastAPI:
    app = FastAPI(title="四口五临边隐患问答助手")
    app.include_router(sessions.router)
    app.include_router(images.router)
    app.include_router(messages.router)
    app.include_router(reports.router)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()

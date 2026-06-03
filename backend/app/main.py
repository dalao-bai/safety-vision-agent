from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import analysis, annotations, chat, files, health, remediations, reports, reviews
from app.core.config import get_settings
from app.db.init import run_migrations


settings = get_settings()

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    if settings.app_env == "development":
        run_migrations()


app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(files.router, prefix="/api/files", tags=["files"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(analysis.router, prefix="/api/analysis", tags=["analysis"])
app.include_router(annotations.router, prefix="/api/annotations", tags=["annotations"])
app.include_router(reviews.router, prefix="/api/reviews", tags=["reviews"])
app.include_router(remediations.router, prefix="/api/remediations", tags=["remediations"])
app.include_router(reports.router, prefix="/api/reports", tags=["reports"])

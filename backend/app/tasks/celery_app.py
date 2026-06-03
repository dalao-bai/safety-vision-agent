from celery import Celery

from app.core.config import get_settings


settings = get_settings()

celery_app = Celery(
    "safety_vision_agent",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks.analysis_tasks", "app.tasks.report_tasks"],
)

celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=False,
)

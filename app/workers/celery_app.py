from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "social_insight_worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max
    worker_concurrency=4,
)

# Placeholder beat schedule for ingestion (will be populated in Phase 4)
celery_app.conf.beat_schedule = {}

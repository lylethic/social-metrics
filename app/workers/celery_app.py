"""Celery application configuration and periodic Beat scheduler for social media data ingestion."""

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "social_insight_worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.workers.tasks_ingestion"],
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

# -------------------------------------------------------------
# Celery Beat Periodic Schedule
# - Channels / Pages: Sync every 6 hours
# - Recent Posts (last 7 days): Sync every 2 hours to catch hot engagement
# -------------------------------------------------------------
celery_app.conf.beat_schedule = {
    "sync-active-channels-periodic": {
        "task": "sync_all_active_channels_task",
        "schedule": crontab(minute=0, hour="*/6"),
        "options": {"expires": 3600},
    },
    "sync-recent-posts-periodic": {
        "task": "sync_all_recent_posts_task",
        "schedule": crontab(minute=0, hour="*/2"),
        "options": {"expires": 3600},
    },
}

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


# -------------------------------------------------------------
# Worker Process Lifecycle & Async Runner
# -------------------------------------------------------------
import asyncio
import logging
from typing import Any, Optional
from celery.signals import worker_process_init, worker_process_shutdown

logger = logging.getLogger(__name__)

_worker_loop: Optional[asyncio.AbstractEventLoop] = None


def get_worker_loop() -> asyncio.AbstractEventLoop:
    """
    Get or create a persistent event loop for the current Celery worker process.
    Reusing the event loop prevents closing and recreating loops across tasks,
    which invalidates SQLAlchemy's connection pool and asyncpg connections.
    """
    global _worker_loop
    if _worker_loop is None or _worker_loop.is_closed():
        _worker_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_worker_loop)
    return _worker_loop


def run_async(coro: Any) -> Any:
    """
    Run an async coroutine synchronously on the persistent worker event loop.
    """
    loop = get_worker_loop()
    return loop.run_until_complete(coro)


@worker_process_init.connect
def on_worker_process_init(**kwargs: Any) -> None:
    """
    Fired when a child worker process is spawned (Celery prefork pool).
    Disposes parent process database connection pool and initializes a fresh event loop
    so child processes do not inherit socket connections from before fork.
    """
    global _worker_loop
    logger.info("[Celery Worker] Initializing worker process lifecycle and event loop...")

    # 1. Dispose parent SQLAlchemy connection pool so child process doesn't inherit open sockets
    try:
        from app.core.database import engine
        engine.sync_engine.dispose(close=False)
    except Exception as exc:
        logger.warning(f"[Celery Worker] Error disposing engine on process init: {exc}")

    # 2. Reset Redis client to avoid sharing socket across process boundaries
    try:
        from app.core import redis as redis_module
        redis_module.redis_client = None
    except Exception as exc:
        logger.warning(f"[Celery Worker] Error resetting Redis client on process init: {exc}")

    # 3. Create fresh event loop for this worker process
    _worker_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_worker_loop)


@worker_process_shutdown.connect
def on_worker_process_shutdown(**kwargs: Any) -> None:
    """
    Fired when a child worker process is terminating.
    Cleans up Redis connection pool, disposes SQLAlchemy engine, and closes the event loop.
    """
    global _worker_loop
    logger.info("[Celery Worker] Shutting down worker process lifecycle...")
    if _worker_loop is not None and not _worker_loop.is_closed():
        try:
            async def _cleanup():
                try:
                    from app.core.redis import close_redis_pool
                    await close_redis_pool()
                except Exception:
                    pass
                try:
                    from app.core.database import engine
                    await engine.dispose()
                except Exception:
                    pass

            _worker_loop.run_until_complete(_cleanup())
        except Exception as exc:
            logger.warning(f"[Celery Worker] Error during worker shutdown cleanup: {exc}")
        finally:
            try:
                _worker_loop.close()
            except Exception:
                pass
            _worker_loop = None


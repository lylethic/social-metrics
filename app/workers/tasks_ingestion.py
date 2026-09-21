"""Celery background tasks for social media data ingestion, snapshot capture, and cache invalidation."""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.metric_snapshot import MetricSnapshot
from app.models.platform_account import PlatformAccount
from app.models.post import Post
from app.services.account_service import account_service
from app.services.analytics_service import calculate_engagement_rate
from app.services.cache_service import cache_service
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


# -------------------------------------------------------------
# Async Implementation Functions (Callable directly or by Tasks)
# -------------------------------------------------------------

async def async_sync_channel_metrics(
    account_id: uuid.UUID,
    db: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    """
    Fetch latest channel profile statistics and record a time-series MetricSnapshot (entity_type='channel').
    Also invalidates Redis insights cache for the account's owner.
    """
    async def _execute(session: AsyncSession) -> Dict[str, Any]:
        account_q = select(PlatformAccount).where(PlatformAccount.id == account_id)
        res = await session.execute(account_q)
        account = res.scalars().first()

        if not account:
            logger.warning(f"[Ingestion] Account {account_id} not found.")
            return {"status": "error", "message": f"Account {account_id} not found."}

        if not account.is_active:
            logger.info(f"[Ingestion] Account {account_id} is inactive. Skipping.")
            return {"status": "skipped", "message": "Account inactive."}

        token = await account_service.get_valid_token(session, account)
        connector = account_service.get_connector(account.platform)

        # 1. Fetch channel profile stats
        profile = await connector.get_channel_profile(
            account_id=account.platform_account_id,
            access_token=token,
        )

        account.account_name = profile.account_name
        account.account_handle = profile.account_handle or account.account_handle
        account.avatar_url = profile.avatar_url or account.avatar_url
        account.metadata_json = profile.metadata_json

        # 2. Record channel snapshot
        snapshot = MetricSnapshot(
            entity_type="channel",
            platform_account_id=account.id,
            views_count=profile.views_count,
            followers_count=profile.followers_count,
            total_videos_count=profile.total_videos_count,
            captured_at=datetime.now(timezone.utc),
        )
        session.add(snapshot)
        await session.commit()

        # 3. Invalidate user's insights cache
        await cache_service.invalidate_user_insights(account.user_id)

        logger.info(
            f"[Ingestion] Channel snapshot recorded for {account.platform}:{account.account_name} "
            f"(Followers: {profile.followers_count}, Views: {profile.views_count})"
        )

        return {
            "status": "success",
            "account_id": str(account.id),
            "platform": account.platform,
            "account_name": account.account_name,
            "followers_count": profile.followers_count,
            "views_count": profile.views_count,
            "total_videos_count": profile.total_videos_count,
            "captured_at": snapshot.captured_at.isoformat(),
        }

    if db is not None:
        return await _execute(db)
    else:
        async with AsyncSessionLocal() as new_session:
            return await _execute(new_session)


async def async_sync_posts_metrics(
    account_id: uuid.UUID,
    limit: int = 50,
    recent_only: bool = False,
    db: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    """
    Fetch posts and their metrics for a connected channel, upsert Post records,
    and save time-series MetricSnapshots (entity_type='post').
    """
    async def _execute(session: AsyncSession) -> Dict[str, Any]:
        account_q = select(PlatformAccount).where(PlatformAccount.id == account_id)
        res = await session.execute(account_q)
        account = res.scalars().first()

        if not account or not account.is_active:
            return {"status": "skipped", "message": "Account missing or inactive."}

        token = await account_service.get_valid_token(session, account)
        connector = account_service.get_connector(account.platform)

        # Determine timeframe: if recent_only, fetch posts from last 7 days
        since = (datetime.now(timezone.utc) - timedelta(days=7)) if recent_only else None

        posts_data = await connector.fetch_posts(
            account_id=account.platform_account_id,
            limit=limit,
            since=since,
            access_token=token,
        )

        synced_posts_count = 0
        for p_data in posts_data:
            # 1. Check if post exists
            post_q = select(Post).where(
                Post.platform_account_id == account.id,
                Post.platform_post_id == p_data.platform_post_id,
            )
            p_res = await session.execute(post_q)
            existing_post = p_res.scalars().first()

            if existing_post:
                existing_post.title = p_data.title
                existing_post.content = p_data.content
                existing_post.thumbnail_url = p_data.thumbnail_url
                existing_post.metadata_json = p_data.metadata_json
                post_record = existing_post
            else:
                post_record = Post(
                    platform_account_id=account.id,
                    platform_post_id=p_data.platform_post_id,
                    post_type=p_data.post_type,
                    title=p_data.title,
                    content=p_data.content,
                    url=p_data.url,
                    thumbnail_url=p_data.thumbnail_url,
                    published_at=p_data.published_at,
                    metadata_json=p_data.metadata_json,
                )
                session.add(post_record)
                await session.flush()

            # 2. Extract or fetch detailed metrics
            meta = p_data.metadata_json or {}
            v_views = meta.get("views_count", 0)
            v_likes = meta.get("likes_count", 0)
            v_comments = meta.get("comments_count", 0)
            v_shares = meta.get("shares_count", 0)
            v_saves = meta.get("saves_count", 0)

            # Try fetching individual post metrics if supported and available
            try:
                detailed_metrics = await connector.fetch_post_metrics(
                    post_id=p_data.platform_post_id,
                    access_token=token,
                )
                if detailed_metrics:
                    v_views = detailed_metrics.views_count or v_views
                    v_likes = detailed_metrics.likes_count or v_likes
                    v_comments = detailed_metrics.comments_count or v_comments
                    v_shares = detailed_metrics.shares_count or v_shares
                    v_saves = detailed_metrics.saves_count or v_saves
            except Exception as exc:
                logger.debug(f"[Ingestion] Individual post metric fetch fallback for {p_data.platform_post_id}: {exc}")

            # Calculate Engagement Rate (ER)
            er = calculate_engagement_rate(
                likes=v_likes,
                comments=v_comments,
                shares=v_shares,
                saves=v_saves,
                views=v_views,
            )

            # 3. Create post snapshot
            post_snapshot = MetricSnapshot(
                entity_type="post",
                platform_account_id=account.id,
                post_id=post_record.id,
                views_count=v_views,
                likes_count=v_likes,
                comments_count=v_comments,
                shares_count=v_shares,
                saves_count=v_saves,
                engagement_rate=er,
                captured_at=datetime.now(timezone.utc),
            )
            session.add(post_snapshot)
            synced_posts_count += 1

        await session.commit()

        # Invalidate insights cache
        await cache_service.invalidate_user_insights(account.user_id)

        logger.info(
            f"[Ingestion] Synced {synced_posts_count} posts and metrics for {account.platform}:{account.account_name}"
        )

        return {
            "status": "success",
            "account_id": str(account.id),
            "platform": account.platform,
            "posts_synced_count": synced_posts_count,
            "recent_only": recent_only,
        }

    if db is not None:
        return await _execute(db)
    else:
        async with AsyncSessionLocal() as new_session:
            return await _execute(new_session)


async def async_sync_all_channels(db: Optional[AsyncSession] = None) -> List[Dict[str, Any]]:
    """Scan all active platform accounts and trigger metrics sync."""
    async def _execute(session: AsyncSession) -> List[Dict[str, Any]]:
        q = select(PlatformAccount).where(PlatformAccount.is_active == True)
        res = await session.execute(q)
        accounts = list(res.scalars().all())

        results = []
        for acc in accounts:
            try:
                # In production worker, this can enqueue tasks:
                # sync_channel_metrics_task.delay(str(acc.id))
                # sync_posts_metrics_task.delay(str(acc.id))
                channel_res = await async_sync_channel_metrics(acc.id, db=session)
                posts_res = await async_sync_posts_metrics(acc.id, limit=30, db=session)
                results.append({"channel": channel_res, "posts": posts_res})
            except Exception as exc:
                logger.error(f"[Ingestion] Failed to sync account {acc.id}: {exc}")
                results.append({"account_id": str(acc.id), "error": str(exc)})
        return results

    if db is not None:
        return await _execute(db)
    else:
        async with AsyncSessionLocal() as new_session:
            return await _execute(new_session)


async def async_sync_all_recent_posts(db: Optional[AsyncSession] = None) -> List[Dict[str, Any]]:
    """Scan all active platform accounts and sync recent posts (past 7 days) for high-velocity engagement."""
    async def _execute(session: AsyncSession) -> List[Dict[str, Any]]:
        q = select(PlatformAccount).where(PlatformAccount.is_active == True)
        res = await session.execute(q)
        accounts = list(res.scalars().all())

        results = []
        for acc in accounts:
            try:
                posts_res = await async_sync_posts_metrics(acc.id, limit=50, recent_only=True, db=session)
                results.append(posts_res)
            except Exception as exc:
                logger.error(f"[Ingestion] Failed to sync recent posts for {acc.id}: {exc}")
                results.append({"account_id": str(acc.id), "error": str(exc)})
        return results

    if db is not None:
        return await _execute(db)
    else:
        async with AsyncSessionLocal() as new_session:
            return await _execute(new_session)


# -------------------------------------------------------------
# Celery Tasks
# -------------------------------------------------------------

@celery_app.task(name="sync_channel_metrics_task", bind=True, max_retries=3, default_retry_delay=60)
def sync_channel_metrics_task(self, account_id: str) -> Dict[str, Any]:
    """Celery task to sync a single channel's profile and record a snapshot."""
    try:
        return asyncio.run(async_sync_channel_metrics(uuid.UUID(account_id)))
    except Exception as exc:
        logger.error(f"[Celery] sync_channel_metrics_task error for {account_id}: {exc}")
        raise self.retry(exc=exc)


@celery_app.task(name="sync_posts_metrics_task", bind=True, max_retries=3, default_retry_delay=60)
def sync_posts_metrics_task(
    self,
    account_id: str,
    limit: int = 50,
    recent_only: bool = False,
) -> Dict[str, Any]:
    """Celery task to sync posts and metrics for a channel."""
    try:
        return asyncio.run(
            async_sync_posts_metrics(uuid.UUID(account_id), limit=limit, recent_only=recent_only)
        )
    except Exception as exc:
        logger.error(f"[Celery] sync_posts_metrics_task error for {account_id}: {exc}")
        raise self.retry(exc=exc)


@celery_app.task(name="sync_all_active_channels_task")
def sync_all_active_channels_task() -> Dict[str, Any]:
    """
    Celery Beat scheduled task: scans all active platform channels and dispatches individual sync tasks.
    Configured to run periodically every 6 hours.
    """
    logger.info("[Celery Beat] Running sync_all_active_channels_task...")
    results = asyncio.run(async_sync_all_channels())
    return {"status": "completed", "total_processed": len(results)}


@celery_app.task(name="sync_all_recent_posts_task")
def sync_all_recent_posts_task() -> Dict[str, Any]:
    """
    Celery Beat scheduled task: scans active channels and updates metrics for posts published in the last 7 days.
    Configured to run periodically every 2 hours to catch fast-moving engagement.
    """
    logger.info("[Celery Beat] Running sync_all_recent_posts_task...")
    results = asyncio.run(async_sync_all_recent_posts())
    return {"status": "completed", "total_processed": len(results)}

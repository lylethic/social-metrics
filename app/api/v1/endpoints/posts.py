"""API Endpoints for Social Media Posts, Content Performance, and Snapshots."""

import uuid
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import NotFoundException
from app.models.platform_account import PlatformAccount
from app.models.post import Post
from app.models.user import User
from app.schemas.metric import (
    MetricSnapshotResponse,
    TopContentResponse,
)
from app.schemas.post import (
    PostListResponse,
    PostWithMetricsResponse,
)
from app.services.analytics_service import analytics_service

router = APIRouter(prefix="/posts", tags=["Posts"])


@router.get("", response_model=PostListResponse, status_code=status.HTTP_200_OK)
async def list_posts(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    platform: Optional[str] = Query(None, description="Filter by platform (youtube, facebook, instagram, threads)"),
    account_id: Optional[uuid.UUID] = Query(None, description="Filter by specific platform account ID"),
    post_type: Optional[str] = Query(None, description="Filter by post type (video, reel, short, photo, text)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
):
    """List social media posts across user's channels with their latest performance metrics."""
    return await analytics_service.get_user_posts(
        db=db,
        user_id=current_user.id,
        platform=platform,
        account_id=account_id,
        post_type=post_type,
        page=page,
        page_size=page_size,
    )


@router.get("/top", response_model=TopContentResponse, status_code=status.HTTP_200_OK)
async def get_top_posts(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    platform: Optional[str] = Query(None, description="Filter by platform name"),
    account_id: Optional[uuid.UUID] = Query(None, description="Filter by specific channel"),
    post_type: Optional[str] = Query(None, description="Filter by post type"),
    limit: int = Query(10, ge=1, le=50, description="Max number of top posts to return"),
    sort_by: str = Query(
        "engagement_rate",
        description="Metric to rank posts by: engagement_rate, views_count, likes_count, comments_count, shares_count",
    ),
    days: int = Query(30, ge=1, le=365, description="Timeframe in days for published posts"),
):
    """Rank posts across all channels by Engagement Rate or other metrics."""
    return await analytics_service.get_top_performing_content(
        db=db,
        user_id=current_user.id,
        platform=platform,
        account_id=account_id,
        post_type=post_type,
        limit=limit,
        sort_by=sort_by,
        days=days,
    )


@router.get("/{post_id}", response_model=PostWithMetricsResponse, status_code=status.HTTP_200_OK)
async def get_post_detail(
    post_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Retrieve details and latest metrics for a specific post."""
    query = (
        select(Post, PlatformAccount)
        .join(PlatformAccount, Post.platform_account_id == PlatformAccount.id)
        .where(
            Post.id == post_id,
            PlatformAccount.user_id == current_user.id,
        )
    )
    result = await db.execute(query)
    record = result.first()

    if not record:
        raise NotFoundException(detail="Post not found.")

    post, account = record
    latest_snap = await analytics_service.get_post_snapshots(db, post.id, days=365)
    latest_snapshot = latest_snap[-1] if latest_snap else None
    snap_resp = MetricSnapshotResponse.model_validate(latest_snapshot) if latest_snapshot else None

    return PostWithMetricsResponse(
        id=post.id,
        platform_account_id=post.platform_account_id,
        platform_post_id=post.platform_post_id,
        post_type=post.post_type,
        title=post.title,
        content=post.content,
        url=post.url,
        thumbnail_url=post.thumbnail_url,
        published_at=post.published_at,
        metadata_json=post.metadata_json,
        created_at=post.created_at,
        updated_at=post.updated_at,
        channel_name=account.account_name,
        platform=account.platform,
        latest_metrics=snap_resp,
    )


@router.get("/{post_id}/snapshots", response_model=List[MetricSnapshotResponse], status_code=status.HTTP_200_OK)
async def get_post_snapshot_history(
    post_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    days: int = Query(30, ge=1, le=365, description="Number of historical days to return"),
):
    """Retrieve time-series snapshots showing metric evolution for a specific post."""
    query = (
        select(Post, PlatformAccount)
        .join(PlatformAccount, Post.platform_account_id == PlatformAccount.id)
        .where(
            Post.id == post_id,
            PlatformAccount.user_id == current_user.id,
        )
    )
    result = await db.execute(query)
    if not result.first():
        raise NotFoundException(detail="Post not found.")

    snapshots = await analytics_service.get_post_snapshots(db, post_id, days=days)
    return snapshots

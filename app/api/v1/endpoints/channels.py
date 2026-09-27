"""API Endpoints for Channels, Channel Metrics, Snapshots, and Growth."""

import uuid
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import (
    BadGatewayException,
    BadRequestException,
    NotFoundException,
    RateLimitException,
)
from app.models.user import User
from app.schemas.metric import (
    ChannelDetailResponse,
    ChannelGrowthResponse,
    MetricSnapshotResponse,
)
from app.schemas.platform import PlatformSyncResponse
from app.services.account_service import account_service
from app.services.analytics_service import analytics_service
from app.services.cache_service import cache_service

router = APIRouter(prefix="/channels", tags=["Channels"])


@router.get("", response_model=List[ChannelDetailResponse], status_code=status.HTTP_200_OK)
async def list_user_channels(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    platform: Optional[str] = Query(None, description="Filter channels by platform name (e.g. youtube, facebook)"),
):
    """List all connected channels for the current user along with their latest metrics and post count."""
    channels = await analytics_service.get_channels_with_metrics(
        db=db,
        user_id=current_user.id,
        platform=platform,
    )
    return channels


@router.get("/{account_id}", response_model=ChannelDetailResponse, status_code=status.HTTP_200_OK)
async def get_channel_detail(
    account_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Retrieve details, latest metrics, and post count for a specific connected channel."""
    account = await account_service.get_by_id(db, account_id, user_id=current_user.id)
    if not account:
        raise NotFoundException(detail="Channel not found.")

    latest_snap = await analytics_service.get_latest_channel_snapshot(db, account.id)
    snap_resp = MetricSnapshotResponse.model_validate(latest_snap) if latest_snap else None

    # Get post count
    from sqlalchemy import func, select
    from app.models.post import Post
    p_count_res = await db.execute(select(func.count(Post.id)).where(Post.platform_account_id == account.id))
    p_count = p_count_res.scalar() or 0

    return ChannelDetailResponse(
        id=account.id,
        platform=account.platform,
        platform_account_id=account.platform_account_id,
        account_name=account.account_name,
        account_handle=account.account_handle,
        avatar_url=account.avatar_url,
        is_active=account.is_active,
        metadata_json=account.metadata_json,
        created_at=account.created_at,
        updated_at=account.updated_at,
        latest_snapshot=snap_resp,
        posts_count=p_count,
    )


@router.get("/{account_id}/snapshots", response_model=List[MetricSnapshotResponse], status_code=status.HTTP_200_OK)
async def get_channel_snapshot_history(
    account_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    days: int = Query(30, ge=1, le=365, description="Number of historical days to return"),
):
    """Retrieve historical time-series metric snapshots for a specific channel."""
    account = await account_service.get_by_id(db, account_id, user_id=current_user.id)
    if not account:
        raise NotFoundException(detail="Channel not found.")

    snapshots = await analytics_service.get_channel_snapshots(db, account.id, days=days)
    return snapshots


@router.get("/{account_id}/growth", response_model=ChannelGrowthResponse, status_code=status.HTTP_200_OK)
async def get_channel_growth_rates(
    account_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Calculate Week-over-Week (WoW) and Month-over-Month (MoM) growth rates for a specific channel."""
    account = await account_service.get_by_id(db, account_id, user_id=current_user.id)
    if not account:
        raise NotFoundException(detail="Channel not found.")

    growth = await analytics_service.get_channel_growth(db, account)
    return growth


@router.post("/{account_id}/sync", response_model=PlatformSyncResponse, status_code=status.HTTP_200_OK)
async def sync_channel(
    account_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(20, ge=1, le=50, description="Max number of recent posts to sync"),
):
    """Trigger manual on-demand data sync for a channel and invalidate cached dashboard data."""
    account = await account_service.get_by_id(db, account_id, user_id=current_user.id)
    if not account:
        raise NotFoundException(detail="Channel not found.")

    try:
        sync_result = await account_service.sync_account_data(db, account, limit_posts=limit)
        await db.commit()

        # Invalidate Redis cache for user
        await cache_service.invalidate_user_insights(current_user.id)

        return sync_result
    except Exception as exc:
        await db.rollback()
        raise BadRequestException(detail=f"Channel synchronization failed: {str(exc)}")

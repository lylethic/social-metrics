"""API Endpoints for Dashboard Insights, Unified Overview, Growth Analytics, and Trends."""

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.metric import (
    GrowthOverviewResponse,
    InsightsSummaryResponse,
    TimeSeriesResponse,
    TopContentResponse,
)
from app.services.analytics_service import analytics_service
from app.services.cache_service import INSIGHTS_CACHE_TTL, cache_service

router = APIRouter(prefix="/insights", tags=["Insights"])


@router.get("/summary", response_model=InsightsSummaryResponse, status_code=status.HTTP_200_OK)
async def get_insights_summary(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    platform: Optional[str] = Query(None, description="Optional platform filter: youtube, facebook, instagram, threads"),
    fresh: bool = Query(False, description="Set True to bypass Redis cache and re-aggregate data"),
):
    """
    Unified Overview API: Aggregates total views, interactions, and followers across all connected platforms.
    Cached in Redis with a 15-minute TTL.
    """
    cache_key = cache_service.build_insights_key(user_id=current_user.id, platform=platform)

    # 1. Check Redis Cache
    if not fresh:
        cached_data = await cache_service.get(cache_key)
        if cached_data is not None:
            cached_data["cached"] = True
            return InsightsSummaryResponse(**cached_data)

    # 2. Compute fresh metrics from database
    summary = await analytics_service.get_unified_overview(
        db=db,
        user_id=current_user.id,
        platform=platform,
    )

    # 3. Store in Redis Cache (TTL = 15 minutes)
    await cache_service.set(
        key=cache_key,
        value=summary.model_dump(mode="json"),
        ttl=INSIGHTS_CACHE_TTL,
    )

    return summary


@router.get("/growth", response_model=GrowthOverviewResponse, status_code=status.HTTP_200_OK)
async def get_growth_analytics(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    platform: Optional[str] = Query(None, description="Optional platform filter"),
):
    """
    Calculate Week-over-Week (WoW) and Month-over-Month (MoM) growth rates
    for followers and views across channels.
    """
    return await analytics_service.get_growth_overview(
        db=db,
        user_id=current_user.id,
        platform=platform,
    )


@router.get("/top-content", response_model=TopContentResponse, status_code=status.HTTP_200_OK)
async def get_top_content(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    platform: Optional[str] = Query(None, description="Filter by platform name"),
    account_id: Optional[uuid.UUID] = Query(None, description="Filter by specific channel"),
    post_type: Optional[str] = Query(None, description="Filter by post type (video, reel, short, photo, text)"),
    limit: int = Query(10, ge=1, le=50, description="Max number of top posts to return"),
    sort_by: str = Query(
        "engagement_rate",
        description="Metric to rank posts by: engagement_rate, views_count, likes_count, comments_count, shares_count",
    ),
    days: int = Query(30, ge=1, le=365, description="Timeframe in days for published content"),
):
    """Rank posts across all channels by Engagement Rate (ER) or other performance metrics."""
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


@router.get("/timeseries", response_model=TimeSeriesResponse, status_code=status.HTTP_200_OK)
async def get_timeseries_metrics(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    platform: Optional[str] = Query(None, description="Filter by platform name"),
    account_id: Optional[uuid.UUID] = Query(None, description="Filter by specific channel"),
    days: int = Query(30, ge=1, le=365, description="Timeframe in days"),
):
    """Daily aggregated metric time-series data points for trend and performance charts."""
    return await analytics_service.get_timeseries_overview(
        db=db,
        user_id=current_user.id,
        platform=platform,
        account_id=account_id,
        days=days,
    )

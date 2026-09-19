"""Pydantic schemas for channel and post metric time-series snapshots and analytics."""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class MetricSnapshotBase(BaseModel):
    """Base schema for snapshot metrics."""
    entity_type: str = Field(..., description="'channel' or 'post'")
    views_count: int = Field(0, description="Total views count at snapshot time")
    likes_count: int = Field(0, description="Total likes count")
    comments_count: int = Field(0, description="Total comments count")
    shares_count: int = Field(0, description="Total shares count")
    saves_count: int = Field(0, description="Total saves count")
    followers_count: int = Field(0, description="Total subscribers or followers count")
    total_videos_count: int = Field(0, description="Total published video/post count")
    engagement_rate: float = Field(0.0, description="Calculated engagement rate percentage")
    watch_time_minutes: float = Field(0.0, description="Total watch time in minutes if available")
    captured_at: Optional[datetime] = None


class MetricSnapshotResponse(MetricSnapshotBase):
    """Public schema for metric snapshot records."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    platform_account_id: Optional[uuid.UUID] = None
    post_id: Optional[uuid.UUID] = None
    captured_at: datetime
    created_at: datetime
    updated_at: datetime


# --- Growth Rate Schemas ---

class GrowthMetric(BaseModel):
    """Growth rate calculation structure."""
    current: int = Field(..., description="Current value")
    baseline: int = Field(..., description="Baseline value from past snapshot")
    change: int = Field(..., description="Absolute change in value")
    growth_rate: float = Field(..., description="Percentage growth rate")
    timeframe: str = Field(..., description="Timeframe of comparison (e.g. 7d, 30d)")


class ChannelGrowthResponse(BaseModel):
    """Growth rate metrics for an individual social channel."""
    channel_id: uuid.UUID
    channel_name: str
    platform: str
    followers_wow: GrowthMetric
    followers_mom: GrowthMetric
    views_wow: Optional[GrowthMetric] = None
    views_mom: Optional[GrowthMetric] = None


class GrowthOverviewResponse(BaseModel):
    """Aggregated growth analytics across channels."""
    followers_wow: GrowthMetric
    followers_mom: GrowthMetric
    channels: List[ChannelGrowthResponse] = Field(default_factory=list)


# --- Unified Overview & Dashboard Schemas ---

class PlatformBreakdownItem(BaseModel):
    """Aggregated stats breakdown by social platform."""
    platform: str
    accounts_count: int = 0
    followers_count: int = 0
    views_count: int = 0
    posts_count: int = 0
    interactions_count: int = 0
    engagement_rate: float = 0.0


class InsightsSummaryResponse(BaseModel):
    """Unified Overview API response schema combining all platforms."""
    total_channels: int = 0
    total_posts: int = 0
    total_followers: int = 0
    total_views: int = 0
    total_interactions: int = 0
    average_engagement_rate: float = 0.0
    platforms: List[PlatformBreakdownItem] = Field(default_factory=list)
    growth: Optional[GrowthOverviewResponse] = None
    cached: bool = False
    generated_at: datetime


# --- Top Performing Content Schemas ---

class TopPostItem(BaseModel):
    """Details of a top-performing post with its metrics."""
    id: uuid.UUID
    platform: str
    platform_post_id: str
    platform_account_id: uuid.UUID
    channel_name: str
    title: Optional[str] = None
    content: Optional[str] = None
    url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    post_type: str = "video"
    published_at: datetime
    views_count: int = 0
    likes_count: int = 0
    comments_count: int = 0
    shares_count: int = 0
    saves_count: int = 0
    engagement_rate: float = 0.0


class TopContentResponse(BaseModel):
    """Response containing ranked top-performing posts."""
    total: int
    sort_by: str
    timeframe_days: int
    items: List[TopPostItem] = Field(default_factory=list)


# --- Time-Series Schemas ---

class TimeSeriesPoint(BaseModel):
    """Single time-series snapshot data point."""
    date: str = Field(..., description="Date formatted as YYYY-MM-DD")
    views_count: int = 0
    followers_count: int = 0
    likes_count: int = 0
    comments_count: int = 0
    shares_count: int = 0
    saves_count: int = 0
    engagement_rate: float = 0.0


class TimeSeriesResponse(BaseModel):
    """Time-series metrics response for chart visualization."""
    timeframe_days: int
    platform: Optional[str] = None
    account_id: Optional[uuid.UUID] = None
    points: List[TimeSeriesPoint] = Field(default_factory=list)


# --- Channel Detail Schema with Metrics ---

class ChannelDetailResponse(BaseModel):
    """Channel information with latest snapshot metrics and post count."""
    id: uuid.UUID
    platform: str
    platform_account_id: str
    account_name: str
    account_handle: Optional[str] = None
    avatar_url: Optional[str] = None
    is_active: bool = True
    metadata_json: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime
    latest_snapshot: Optional[MetricSnapshotResponse] = None
    posts_count: int = 0

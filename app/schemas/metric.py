"""Pydantic schemas for channel and post metric time-series snapshots."""

import uuid
from datetime import datetime
from typing import Optional
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

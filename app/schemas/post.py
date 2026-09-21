"""Pydantic schemas for social media posts, videos, and content items."""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.metric import MetricSnapshotResponse


class PostBase(BaseModel):
    """Base schema for social post data."""
    platform_post_id: str = Field(..., description="External post/video ID from the social platform")
    post_type: str = Field("video", description="Type of post: video, short, reel, photo, text, thread")
    title: Optional[str] = None
    content: Optional[str] = None
    url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    published_at: datetime
    metadata_json: Optional[Dict[str, Any]] = None


class PostCreate(PostBase):
    """Schema for creating a post record."""
    platform_account_id: uuid.UUID


class PostResponse(PostBase):
    """Public schema for post response."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    platform_account_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class PostWithMetricsResponse(PostResponse):
    """Post response enriched with channel details and latest snapshot metrics."""
    channel_name: Optional[str] = None
    platform: Optional[str] = None
    latest_metrics: Optional[MetricSnapshotResponse] = None


class PostListResponse(BaseModel):
    """Paginated list of posts."""
    total: int
    page: int
    page_size: int
    items: List[PostWithMetricsResponse] = Field(default_factory=list)

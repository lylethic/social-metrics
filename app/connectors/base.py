"""Abstract Base Social Media Connector interface and standardized data transfer schemas."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# --- Domain Exceptions for Connectors ---

class ConnectorError(Exception):
    """Base exception for all social media connector errors."""

    def __init__(self, message: str, platform: str = "unknown", original_error: Optional[Exception] = None):
        super().__init__(message)
        self.message = message
        self.platform = platform
        self.original_error = original_error

    def __str__(self) -> str:
        return f"[{self.platform.upper()}] {self.message}"


class ConnectorAuthError(ConnectorError):
    """Raised when authentication, token exchange, or authorization fails."""
    pass


class ConnectorRateLimitError(ConnectorError):
    """Raised when upstream API rate limits are hit (HTTP 429)."""

    def __init__(
        self,
        message: str = "Rate limit reached",
        platform: str = "unknown",
        retry_after: Optional[int] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(message, platform=platform, original_error=original_error)
        self.retry_after = retry_after


class ConnectorQuotaExceededError(ConnectorError):
    """Raised when upstream API quota (e.g., YouTube daily 10,000 units) is exhausted."""
    pass


class ConnectorNotFoundError(ConnectorError):
    """Raised when a requested channel, post, or media item is not found (HTTP 404)."""
    pass


class ConnectorAPIError(ConnectorError):
    """Raised when upstream API returns an unexpected error (HTTP 4xx/5xx)."""

    def __init__(
        self,
        message: str,
        platform: str = "unknown",
        status_code: Optional[int] = None,
        raw_response: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(message, platform=platform, original_error=original_error)
        self.status_code = status_code
        self.raw_response = raw_response


# --- Standardized Data Transfer Schemas ---

class OAuthTokenResponse(BaseModel):
    """Standardized response from OAuth authorization code or refresh token exchange."""
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "Bearer"
    expires_in: Optional[int] = None  # in seconds
    scope: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None


class ChannelProfile(BaseModel):
    """Standardized channel/page profile schema across social platforms."""
    platform: str
    platform_account_id: str
    account_name: str
    account_handle: Optional[str] = None
    avatar_url: Optional[str] = None
    followers_count: int = 0  # Subscribers, followers, or page fans
    views_count: int = 0      # Total channel/page views if available
    total_videos_count: int = 0
    metadata_json: Dict[str, Any] = Field(default_factory=dict)


class PlatformPost(BaseModel):
    """Standardized post/video/reel schema across social platforms."""
    platform: str
    platform_post_id: str
    platform_account_id: str
    post_type: str = "video"  # video, short, reel, photo, text, thread
    title: Optional[str] = None
    content: Optional[str] = None
    url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    published_at: datetime
    metadata_json: Dict[str, Any] = Field(default_factory=dict)


class PostMetrics(BaseModel):
    """Standardized snapshot metrics for an individual post."""
    platform_post_id: str
    views_count: int = 0
    likes_count: int = 0
    comments_count: int = 0
    shares_count: int = 0
    saves_count: int = 0
    engagement_rate: float = 0.0
    watch_time_minutes: float = 0.0
    captured_at: Optional[datetime] = None


class PlatformComment(BaseModel):
    """Standardized comment structure across platforms."""
    comment_id: str
    platform_post_id: str
    author_name: str
    author_avatar_url: Optional[str] = None
    author_channel_url: Optional[str] = None
    content: str
    likes_count: int = 0
    published_at: datetime
    reply_count: int = 0


# --- Abstract Base Connector ---

class BaseSocialConnector(ABC):
    """Abstract Base Class defining the contract for all social media connectors."""

    platform_name: str = "base"

    @abstractmethod
    def get_authorization_url(self, state: str, redirect_uri: Optional[str] = None) -> str:
        """Generate platform OAuth2 authorization consent URL."""
        pass

    @abstractmethod
    async def authenticate(self, auth_code: str, redirect_uri: Optional[str] = None) -> OAuthTokenResponse:
        """Exchange authorization code for access and refresh tokens."""
        pass

    @abstractmethod
    async def refresh_token(self, refresh_token: str) -> OAuthTokenResponse:
        """Refresh expired access token using refresh token."""
        pass

    @abstractmethod
    async def get_channel_profile(
        self,
        account_id: str,
        access_token: Optional[str] = None,
    ) -> ChannelProfile:
        """Fetch channel or page profile information."""
        pass

    @abstractmethod
    async def fetch_posts(
        self,
        account_id: str,
        limit: int = 50,
        since: Optional[datetime] = None,
        access_token: Optional[str] = None,
    ) -> List[PlatformPost]:
        """Fetch recent posts, videos, or reels published by the channel/page."""
        pass

    @abstractmethod
    async def fetch_post_metrics(
        self,
        post_id: str,
        access_token: Optional[str] = None,
    ) -> PostMetrics:
        """Fetch current metrics (views, likes, comments, shares) for a specific post."""
        pass

    @abstractmethod
    async def fetch_comments(
        self,
        post_id: str,
        limit: int = 50,
        access_token: Optional[str] = None,
    ) -> List[PlatformComment]:
        """Fetch comments for a specific post or video."""
        pass

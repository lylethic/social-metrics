"""Pydantic schemas for social platform accounts and OAuth flows."""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class PlatformAccountBase(BaseModel):
    """Base schema for social platform accounts."""
    platform: str = Field(..., description="Platform identifier: youtube, facebook, instagram, threads, tiktok")
    platform_account_id: str = Field(..., description="Unique platform account/channel ID")
    account_name: str = Field(..., description="Display name of the channel or page")
    account_handle: Optional[str] = Field(None, description="Platform handle e.g. @channel_handle")
    avatar_url: Optional[str] = Field(None, description="URL to channel or profile avatar")
    is_active: bool = Field(True, description="Whether this account is actively synced")


class PlatformAccountCreate(PlatformAccountBase):
    """Schema for manually registering or connecting a platform account."""
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_expires_at: Optional[datetime] = None
    metadata_json: Optional[Dict[str, Any]] = None


class PlatformAccountUpdate(BaseModel):
    """Schema for updating platform account metadata or status."""
    account_name: Optional[str] = None
    account_handle: Optional[str] = None
    avatar_url: Optional[str] = None
    is_active: Optional[bool] = None
    metadata_json: Optional[Dict[str, Any]] = None


class PlatformAccountResponse(PlatformAccountBase):
    """Public representation of connected platform account (tokens are stripped for security)."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    token_expires_at: Optional[datetime] = None
    metadata_json: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime


class OAuthAuthorizeUrlResponse(BaseModel):
    """Response containing platform OAuth consent redirect URL."""
    platform: str
    authorization_url: str
    state: str


class OAuthCallbackRequest(BaseModel):
    """OAuth callback query payload."""
    code: str = Field(..., description="Authorization code returned by OAuth provider")
    state: Optional[str] = Field(None, description="Anti-CSRF state token")
    redirect_uri: Optional[str] = Field(None, description="Redirect URI matching authorization request")


class ConnectWithChannelIdRequest(BaseModel):
    """Connect a YouTube channel by ID or Handle directly (using API Key or existing OAuth)."""
    channel_id: str = Field(..., description="Channel ID (UC...) or handle (@username)")


class PlatformSyncResponse(BaseModel):
    """Summary of on-demand synchronization execution."""
    platform_account_id: uuid.UUID
    platform: str
    channel_name: str
    posts_synced_count: int
    followers_count: int
    views_count: int
    synced_at: datetime


class FacebookPageItem(BaseModel):
    """Details of a Facebook Page retrieved via Meta Graph API."""
    id: str
    name: str
    category: Optional[str] = None
    avatar_url: Optional[str] = None
    instagram_business_account_id: Optional[str] = None
    instagram_username: Optional[str] = None


class FacebookConnectPageRequest(BaseModel):
    """Request to link a specific Facebook Page by its Page ID."""
    page_id: str = Field(..., description="Facebook Page ID to connect")
    user_access_token: Optional[str] = Field(None, description="Optional long-lived user access token if not stored")


class InstagramConnectRequest(BaseModel):
    """Request to connect an Instagram Business/Creator Account."""
    instagram_account_id: str = Field(..., description="Instagram Business Account ID")
    page_id: Optional[str] = Field(None, description="Facebook Page ID linked to this Instagram account")
    user_access_token: Optional[str] = Field(None, description="Optional access token")

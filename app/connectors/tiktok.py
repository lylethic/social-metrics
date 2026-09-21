"""Official TikTok for Developers (v2 Display & Login Kit) Connector implementing BaseSocialConnector.

Handles TikTok OAuth2 consent flow, access/refresh token lifecycle,
creator profile metadata and stats, video list ingestion, and engagement metrics.
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx

from app.connectors.base import (
    BaseSocialConnector,
    ChannelProfile,
    ConnectorAPIError,
    ConnectorAuthError,
    ConnectorNotFoundError,
    ConnectorRateLimitError,
    OAuthTokenResponse,
    PlatformComment,
    PlatformPost,
    PostMetrics,
)
from app.core.config import settings
from app.services.analytics_service import calculate_engagement_rate

logger = logging.getLogger(__name__)


class TikTokConnector(BaseSocialConnector):
    """Connector for Official TikTok API v2 (open.tiktokapis.com/v2/)."""

    platform_name: str = "tiktok"

    TIKTOK_AUTH_BASE_URL = "https://www.tiktok.com/v2/auth/authorize/"
    TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
    TIKTOK_API_BASE_URL = "https://open.tiktokapis.com/v2"

    DEFAULT_SCOPES = [
        "user.info.basic",
        "user.info.profile",
        "user.info.stats",
        "video.list",
    ]

    def __init__(
        self,
        client_key: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
    ):
        self.client_key = client_key or settings.TIKTOK_CLIENT_KEY
        self.client_secret = client_secret or settings.TIKTOK_CLIENT_SECRET
        self.redirect_uri = redirect_uri or settings.TIKTOK_REDIRECT_URI
        self.auth_base_url = settings.TIKTOK_AUTH_BASE_URL or self.TIKTOK_AUTH_BASE_URL
        self.token_url = settings.TIKTOK_TOKEN_URL or self.TIKTOK_TOKEN_URL
        self.api_base_url = (settings.TIKTOK_API_BASE_URL or self.TIKTOK_API_BASE_URL).rstrip("/")
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

    def get_authorization_url(self, state: str, redirect_uri: Optional[str] = None) -> str:
        """Generate TikTok OAuth2 authorization consent URL."""
        if not self.client_key:
            raise ConnectorAuthError(
                "TikTok client_key is not configured",
                platform=self.platform_name,
            )

        params = {
            "client_key": self.client_key,
            "scope": ",".join(self.DEFAULT_SCOPES),
            "response_type": "code",
            "redirect_uri": redirect_uri or self.redirect_uri,
            "state": state,
        }
        return f"{self.auth_base_url}?{urlencode(params)}"

    async def authenticate(self, auth_code: str, redirect_uri: Optional[str] = None) -> OAuthTokenResponse:
        """Exchange authorization code for access and refresh tokens."""
        if not self.client_key or not self.client_secret:
            raise ConnectorAuthError(
                "TikTok client_key or client_secret is not configured",
                platform=self.platform_name,
            )

        payload = {
            "client_key": self.client_key,
            "client_secret": self.client_secret,
            "code": auth_code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri or self.redirect_uri,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    self.token_url,
                    data=payload,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                data = response.json()

                error_info = data.get("error", {})
                error_code = error_info.get("code") if isinstance(error_info, dict) else data.get("error")

                if response.status_code != 200 or (error_code and error_code not in ("ok", 0, "0")):
                    err_msg = ""
                    if isinstance(error_info, dict):
                        err_msg = error_info.get("message") or str(error_info)
                    else:
                        err_msg = data.get("error_description") or str(data)

                    raise ConnectorAuthError(
                        f"TikTok OAuth exchange failed: {err_msg}",
                        platform=self.platform_name,
                    )

                token_data = data.get("data", data)
                access_token = token_data.get("access_token")
                if not access_token:
                    raise ConnectorAuthError(
                        "No access_token returned by TikTok token endpoint",
                        platform=self.platform_name,
                    )

                return OAuthTokenResponse(
                    access_token=access_token,
                    refresh_token=token_data.get("refresh_token"),
                    token_type=token_data.get("token_type", "Bearer"),
                    expires_in=token_data.get("expires_in", 86400),
                    scope=token_data.get("scope"),
                    raw_response=data,
                )

        except (ConnectorAuthError, ConnectorAPIError):
            raise
        except httpx.RequestError as exc:
            raise ConnectorAuthError(
                f"Network error during TikTok authentication: {str(exc)}",
                platform=self.platform_name,
                original_error=exc,
            )

    async def refresh_token(self, refresh_token: str) -> OAuthTokenResponse:
        """Refresh expired access token using TikTok refresh token."""
        if not self.client_key or not self.client_secret:
            raise ConnectorAuthError(
                "TikTok client_key or client_secret is not configured",
                platform=self.platform_name,
            )

        payload = {
            "client_key": self.client_key,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    self.token_url,
                    data=payload,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                data = response.json()

                error_info = data.get("error", {})
                error_code = error_info.get("code") if isinstance(error_info, dict) else data.get("error")

                if response.status_code != 200 or (error_code and error_code not in ("ok", 0, "0")):
                    err_msg = ""
                    if isinstance(error_info, dict):
                        err_msg = error_info.get("message") or str(error_info)
                    else:
                        err_msg = data.get("error_description") or str(data)

                    raise ConnectorAuthError(
                        f"TikTok token refresh failed: {err_msg}",
                        platform=self.platform_name,
                    )

                token_data = data.get("data", data)
                access_token = token_data.get("access_token")
                if not access_token:
                    raise ConnectorAuthError(
                        "No access_token returned by TikTok refresh endpoint",
                        platform=self.platform_name,
                    )

                return OAuthTokenResponse(
                    access_token=access_token,
                    refresh_token=token_data.get("refresh_token", refresh_token),
                    token_type=token_data.get("token_type", "Bearer"),
                    expires_in=token_data.get("expires_in", 86400),
                    scope=token_data.get("scope"),
                    raw_response=data,
                )
        except (ConnectorAuthError, ConnectorAPIError):
            raise
        except httpx.RequestError as exc:
            raise ConnectorAuthError(
                f"Network error refreshing TikTok token: {str(exc)}",
                platform=self.platform_name,
                original_error=exc,
            )

    async def get_channel_profile(
        self,
        account_id: str,
        access_token: Optional[str] = None,
    ) -> ChannelProfile:
        """Fetch TikTok user profile information and basic statistics."""
        if not access_token:
            raise ConnectorAuthError(
                "Access token is required to fetch TikTok profile",
                platform=self.platform_name,
            )

        fields = (
            "open_id,union_id,avatar_url,avatar_large_url,display_name,"
            "bio_description,profile_deep_link,is_verified,follower_count,"
            "following_count,likes_count,video_count"
        )
        endpoint = f"/user/info/?fields={fields}"
        data = await self._make_request(endpoint=endpoint, access_token=access_token, method="GET")

        user_info = data.get("data", {}).get("user", {})
        if not user_info:
            raise ConnectorNotFoundError(
                f"TikTok user profile not found for account {account_id}",
                platform=self.platform_name,
            )

        open_id = str(user_info.get("open_id") or account_id)
        display_name = user_info.get("display_name") or f"TikTok Creator ({open_id[:8]})"
        profile_url = user_info.get("profile_deep_link") or ""

        # Extract handle e.g. @username from deep link if present
        account_handle = None
        if profile_url:
            match = re.search(r"tiktok\.com/@([^/?#]+)", profile_url)
            if match:
                account_handle = f"@{match.group(1)}"

        avatar_url = user_info.get("avatar_large_url") or user_info.get("avatar_url")
        followers_count = int(user_info.get("follower_count") or 0)
        total_videos = int(user_info.get("video_count") or 0)

        metadata = {
            "open_id": open_id,
            "union_id": user_info.get("union_id"),
            "bio_description": user_info.get("bio_description"),
            "profile_deep_link": profile_url,
            "is_verified": user_info.get("is_verified", False),
            "following_count": int(user_info.get("following_count") or 0),
            "likes_count": int(user_info.get("likes_count") or 0),
        }

        return ChannelProfile(
            platform=self.platform_name,
            platform_account_id=open_id,
            account_name=display_name,
            account_handle=account_handle,
            avatar_url=avatar_url,
            followers_count=followers_count,
            views_count=0,  # TikTok user info doesn't provide channel-wide views; aggregated from posts
            total_videos_count=total_videos,
            metadata_json=metadata,
        )

    async def fetch_posts(
        self,
        account_id: str,
        limit: int = 20,
        since: Optional[datetime] = None,
        access_token: Optional[str] = None,
    ) -> List[PlatformPost]:
        """Fetch recent TikTok videos published by the creator."""
        if not access_token:
            raise ConnectorAuthError(
                "Access token is required to fetch TikTok posts",
                platform=self.platform_name,
            )

        fields = (
            "id,create_time,cover_image_url,share_url,video_description,"
            "duration,height,width,title,like_count,comment_count,share_count,view_count"
        )
        endpoint = f"/video/list/?fields={fields}"
        payload = {"max_count": min(max(1, limit), 20)}

        data = await self._make_request(
            endpoint=endpoint,
            json_body=payload,
            access_token=access_token,
            method="POST",
        )

        videos_raw = data.get("data", {}).get("videos", [])
        posts: List[PlatformPost] = []

        for v in videos_raw:
            vid = str(v.get("id") or "")
            if not vid:
                continue

            create_time = v.get("create_time")
            if create_time:
                published_at = datetime.fromtimestamp(int(create_time), tz=timezone.utc)
            else:
                published_at = datetime.now(timezone.utc)

            if since and published_at < since:
                continue

            title = v.get("title")
            desc = v.get("video_description") or ""
            if not title:
                title = desc[:60].strip() if desc else "TikTok Video"

            v_views = int(v.get("view_count") or 0)
            v_likes = int(v.get("like_count") or 0)
            v_comments = int(v.get("comment_count") or 0)
            v_shares = int(v.get("share_count") or 0)

            metadata = {
                "views_count": v_views,
                "likes_count": v_likes,
                "comments_count": v_comments,
                "shares_count": v_shares,
                "saves_count": 0,
                "duration": v.get("duration", 0),
                "height": v.get("height"),
                "width": v.get("width"),
            }

            post = PlatformPost(
                platform=self.platform_name,
                platform_post_id=vid,
                platform_account_id=account_id,
                post_type="video",
                title=title,
                content=desc,
                url=v.get("share_url"),
                thumbnail_url=v.get("cover_image_url"),
                published_at=published_at,
                metadata_json=metadata,
            )
            posts.append(post)

            if len(posts) >= limit:
                break

        return posts

    async def fetch_post_metrics(
        self,
        post_id: str,
        access_token: Optional[str] = None,
    ) -> PostMetrics:
        """Fetch current metrics (views, likes, comments, shares) for a specific TikTok video."""
        if not access_token:
            raise ConnectorAuthError(
                "Access token is required to fetch TikTok post metrics",
                platform=self.platform_name,
            )

        fields = "id,like_count,comment_count,share_count,view_count"
        endpoint = f"/video/query/?fields={fields}"
        payload = {"filters": {"video_ids": [post_id]}}

        views_count = 0
        likes_count = 0
        comments_count = 0
        shares_count = 0

        try:
            data = await self._make_request(
                endpoint=endpoint,
                json_body=payload,
                access_token=access_token,
                method="POST",
            )
            videos = data.get("data", {}).get("videos", [])
            if videos:
                v = videos[0]
                views_count = int(v.get("view_count") or 0)
                likes_count = int(v.get("like_count") or 0)
                comments_count = int(v.get("comment_count") or 0)
                shares_count = int(v.get("share_count") or 0)
        except Exception as exc:
            logger.debug(f"Could not fetch metrics for TikTok video {post_id}: {exc}")

        er = calculate_engagement_rate(
            likes=likes_count,
            comments=comments_count,
            shares=shares_count,
            saves=0,
            views=views_count,
        )

        return PostMetrics(
            platform_post_id=post_id,
            views_count=views_count,
            likes_count=likes_count,
            comments_count=comments_count,
            shares_count=shares_count,
            saves_count=0,
            engagement_rate=er,
            captured_at=datetime.now(timezone.utc),
        )

    async def fetch_comments(
        self,
        post_id: str,
        limit: int = 50,
        access_token: Optional[str] = None,
    ) -> List[PlatformComment]:
        """Fetch comments for a TikTok video.

        Note: Standard TikTok Display API v2 does not provide a public comment reading endpoint.
        Returns an empty list by design to preserve interface compatibility.
        """
        logger.info(
            f"TikTok comment reading is not supported by Display API v2 for video {post_id}. Returning empty list."
        )
        return []

    async def _make_request(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        access_token: Optional[str] = None,
        method: str = "GET",
    ) -> Dict[str, Any]:
        """Execute HTTP request to TikTok API with retry and backoff."""
        cleaned_endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        url = f"{self.api_base_url}{cleaned_endpoint}"
        headers = {
            "Accept": "application/json",
        }
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"

        last_exception: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    if method.upper() == "POST":
                        headers["Content-Type"] = "application/json"
                        response = await client.post(url, params=params, json=json_body, headers=headers)
                    else:
                        response = await client.get(url, params=params, headers=headers)

                    # Handle 429 Rate Limit
                    if response.status_code == 429:
                        retry_after = int(response.headers.get("Retry-After", 2 ** attempt))
                        if attempt < self.max_retries:
                            await asyncio.sleep(retry_after * self.backoff_factor)
                            continue
                        raise ConnectorRateLimitError(
                            "TikTok API rate limit exceeded",
                            platform=self.platform_name,
                            retry_after=retry_after,
                        )

                    data = response.json()
                    error_info = data.get("error", {})
                    error_code = error_info.get("code") if isinstance(error_info, dict) else data.get("error")

                    # Handle TikTok error payloads
                    if error_code and error_code not in ("ok", 0, "0"):
                        err_msg = error_info.get("message") if isinstance(error_info, dict) else str(error_info)
                        if error_code in ("access_token_invalid", "token_expired", "invalid_grant", "scope_not_authorized"):
                            raise ConnectorAuthError(f"TikTok Auth error: {err_msg}", platform=self.platform_name)
                        if error_code in ("rate_limit_exceeded", "spam_risk_user"):
                            raise ConnectorRateLimitError(f"TikTok Rate limit: {err_msg}", platform=self.platform_name)
                        if error_code in ("user_not_found", "video_not_found"):
                            raise ConnectorNotFoundError(f"TikTok Not found: {err_msg}", platform=self.platform_name)

                        raise ConnectorAPIError(
                            f"TikTok API error ({error_code}): {err_msg}",
                            platform=self.platform_name,
                            status_code=response.status_code,
                            raw_response=data,
                        )

                    if response.status_code == 401:
                        raise ConnectorAuthError("TikTok token expired or invalid", platform=self.platform_name)
                    if response.status_code == 404:
                        raise ConnectorNotFoundError("Resource not found on TikTok", platform=self.platform_name)
                    if response.status_code >= 400:
                        raise ConnectorAPIError(
                            f"TikTok API returned HTTP {response.status_code}",
                            platform=self.platform_name,
                            status_code=response.status_code,
                            raw_response=data,
                        )

                    return data

            except (ConnectorRateLimitError, ConnectorAuthError, ConnectorNotFoundError, ConnectorAPIError):
                raise
            except httpx.RequestError as exc:
                last_exception = exc
                if attempt < self.max_retries:
                    await asyncio.sleep((2 ** attempt) * self.backoff_factor)
                    continue
                raise ConnectorAPIError(
                    f"Network error communicating with TikTok: {str(exc)}",
                    platform=self.platform_name,
                    original_error=exc,
                )

        raise ConnectorAPIError(
            f"Failed after {self.max_retries} retries: {str(last_exception)}",
            platform=self.platform_name,
            original_error=last_exception,
        )

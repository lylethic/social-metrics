"""YouTube Data API v3 Connector implementing BaseSocialConnector.

Handles OAuth2 token exchange, channel metadata, playlist uploads, video statistics,
comment threads, and exponential backoff retry for quota and rate limits.
"""

import asyncio
import logging
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
    ConnectorQuotaExceededError,
    ConnectorRateLimitError,
    OAuthTokenResponse,
    PlatformComment,
    PlatformPost,
    PostMetrics,
)
from app.core.config import settings

logger = logging.getLogger(__name__)


class YouTubeConnector(BaseSocialConnector):
    """Connector for YouTube Data API v3."""

    platform_name: str = "youtube"

    GOOGLE_AUTH_BASE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
    YOUTUBE_API_BASE_URL = "https://www.googleapis.com/youtube/v3"

    DEFAULT_SCOPES = [
        "https://www.googleapis.com/auth/youtube.readonly",
        "openid",
        "email",
        "profile",
    ]

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        api_key: Optional[str] = None,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
    ):
        self.client_id = client_id or settings.YOUTUBE_CLIENT_ID
        self.client_secret = client_secret or settings.YOUTUBE_CLIENT_SECRET
        self.redirect_uri = redirect_uri or settings.YOUTUBE_REDIRECT_URI
        self.api_key = api_key or settings.YOUTUBE_API_KEY
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

    def get_authorization_url(self, state: str, redirect_uri: Optional[str] = None) -> str:
        """Generate Google OAuth2 consent URL for YouTube scopes."""
        if not self.client_id:
            raise ConnectorAuthError(
                "YouTube client_id is not configured",
                platform=self.platform_name,
            )

        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri or self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.DEFAULT_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{self.GOOGLE_AUTH_BASE_URL}?{urlencode(params)}"

    async def authenticate(self, auth_code: str, redirect_uri: Optional[str] = None) -> OAuthTokenResponse:
        """Exchange authorization code for access and refresh tokens."""
        if not self.client_id or not self.client_secret:
            raise ConnectorAuthError(
                "YouTube client_id or client_secret is not configured",
                platform=self.platform_name,
            )

        payload = {
            "code": auth_code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": redirect_uri or self.redirect_uri,
            "grant_type": "authorization_code",
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(self.GOOGLE_TOKEN_URL, data=payload)
                data = response.json()

                if response.status_code != 200:
                    error_desc = data.get("error_description") or data.get("error") or "Failed to exchange code"
                    raise ConnectorAuthError(
                        f"OAuth exchange failed ({response.status_code}): {error_desc}",
                        platform=self.platform_name,
                    )

                return OAuthTokenResponse(
                    access_token=data["access_token"],
                    refresh_token=data.get("refresh_token"),
                    token_type=data.get("token_type", "Bearer"),
                    expires_in=data.get("expires_in"),
                    scope=data.get("scope"),
                    raw_response=data,
                )
        except httpx.RequestError as exc:
            raise ConnectorAuthError(
                f"Network error during OAuth token exchange: {str(exc)}",
                platform=self.platform_name,
                original_error=exc,
            )

    async def refresh_token(self, refresh_token: str) -> OAuthTokenResponse:
        """Refresh an expired YouTube access token."""
        if not self.client_id or not self.client_secret:
            raise ConnectorAuthError(
                "YouTube client_id or client_secret is not configured",
                platform=self.platform_name,
            )

        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(self.GOOGLE_TOKEN_URL, data=payload)
                data = response.json()

                if response.status_code != 200:
                    error_desc = data.get("error_description") or data.get("error") or "Failed to refresh token"
                    raise ConnectorAuthError(
                        f"Token refresh failed ({response.status_code}): {error_desc}",
                        platform=self.platform_name,
                    )

                return OAuthTokenResponse(
                    access_token=data["access_token"],
                    refresh_token=data.get("refresh_token") or refresh_token,
                    token_type=data.get("token_type", "Bearer"),
                    expires_in=data.get("expires_in"),
                    scope=data.get("scope"),
                    raw_response=data,
                )
        except httpx.RequestError as exc:
            raise ConnectorAuthError(
                f"Network error during token refresh: {str(exc)}",
                platform=self.platform_name,
                original_error=exc,
            )

    async def _make_request(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        access_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute HTTP GET request to YouTube Data API with exponential backoff retry."""
        url = f"{self.YOUTUBE_API_BASE_URL}{endpoint}"
        query_params = dict(params or {})

        headers = {
            "Accept": "application/json",
        }

        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        elif self.api_key:
            query_params["key"] = self.api_key
        else:
            raise ConnectorAuthError(
                "Neither access_token nor api_key was provided for YouTube request",
                platform=self.platform_name,
            )

        last_exception: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    response = await client.get(url, params=query_params, headers=headers)
                    status = response.status_code

                    # Check for rate limit or transient errors eligible for retry
                    if status in (429, 500, 502, 503, 504):
                        if attempt < self.max_retries:
                            delay = self.backoff_factor * (2 ** attempt)
                            retry_after = response.headers.get("Retry-After")
                            if retry_after and retry_after.isdigit():
                                delay = max(delay, float(retry_after))
                            logger.warning(
                                f"YouTube API returned {status}. Retrying in {delay:.2f}s (attempt {attempt + 1}/{self.max_retries})"
                            )
                            await asyncio.sleep(delay)
                            continue

                    # Parse response body
                    try:
                        data = response.json()
                    except Exception:
                        data = {"raw": response.text}

                    if status == 200:
                        return data

                    # Handle error specifics
                    error_obj = data.get("error", {})
                    errors_list = error_obj.get("errors", [])
                    reasons = [e.get("reason", "") for e in errors_list]
                    message = error_obj.get("message", f"HTTP {status} from YouTube API")

                    if status == 403:
                        if "quotaExceeded" in reasons or "dailyLimitExceeded" in reasons:
                            raise ConnectorQuotaExceededError(
                                f"YouTube API quota exceeded (10,000 units/day limit reached): {message}",
                                platform=self.platform_name,
                            )
                        if "rateLimitExceeded" in reasons or "userRateLimitExceeded" in reasons:
                            if attempt < self.max_retries:
                                delay = self.backoff_factor * (2 ** attempt)
                                await asyncio.sleep(delay)
                                continue
                            raise ConnectorRateLimitError(
                                f"YouTube API rate limit exceeded: {message}",
                                platform=self.platform_name,
                            )
                        raise ConnectorAPIError(
                            f"YouTube API Forbidden (403): {message}",
                            platform=self.platform_name,
                            status_code=403,
                            raw_response=data,
                        )

                    if status == 401:
                        raise ConnectorAuthError(
                            f"YouTube authorization error (401): {message}",
                            platform=self.platform_name,
                        )

                    if status == 404:
                        raise ConnectorNotFoundError(
                            f"YouTube resource not found (404): {message}",
                            platform=self.platform_name,
                        )

                    if status == 429:
                        raise ConnectorRateLimitError(
                            f"YouTube rate limit hit (429): {message}",
                            platform=self.platform_name,
                        )

                    raise ConnectorAPIError(
                        f"YouTube API error ({status}): {message}",
                        platform=self.platform_name,
                        status_code=status,
                        raw_response=data,
                    )

            except (httpx.ConnectError, httpx.TimeoutException, httpx.ReadTimeout) as exc:
                last_exception = exc
                if attempt < self.max_retries:
                    delay = self.backoff_factor * (2 ** attempt)
                    logger.warning(
                        f"YouTube request network error: {exc}. Retrying in {delay:.2f}s (attempt {attempt + 1}/{self.max_retries})"
                    )
                    await asyncio.sleep(delay)
                    continue
                raise ConnectorAPIError(
                    f"Network error connecting to YouTube API: {str(exc)}",
                    platform=self.platform_name,
                    original_error=exc,
                )

        if last_exception:
            raise ConnectorAPIError(
                f"Failed YouTube API request after retries: {str(last_exception)}",
                platform=self.platform_name,
                original_error=last_exception,
            )

        raise ConnectorAPIError("Unexpected termination of request loop", platform=self.platform_name)

    async def get_channel_profile(
        self,
        account_id: str,
        access_token: Optional[str] = None,
    ) -> ChannelProfile:
        """Fetch YouTube channel profile statistics and upload playlist."""
        params: Dict[str, Any] = {
            "part": "snippet,statistics,contentDetails",
        }

        # Resolve channel identifier query parameter
        if account_id == "mine" or not account_id:
            params["mine"] = "true"
        elif account_id.startswith("@"):
            params["forHandle"] = account_id
        elif account_id.startswith("UC"):
            params["id"] = account_id
        else:
            params["id"] = account_id

        data = await self._make_request("/channels", params=params, access_token=access_token)
        items = data.get("items", [])
        if not items:
            raise ConnectorNotFoundError(
                f"YouTube channel '{account_id}' not found",
                platform=self.platform_name,
            )

        item = items[0]
        snippet = item.get("snippet", {})
        statistics = item.get("statistics", {})
        content_details = item.get("contentDetails", {})
        related_playlists = content_details.get("relatedPlaylists", {})
        uploads_playlist_id = related_playlists.get("uploads")

        thumbnails = snippet.get("thumbnails", {})
        avatar_url = (
            thumbnails.get("high", {}).get("url")
            or thumbnails.get("medium", {}).get("url")
            or thumbnails.get("default", {}).get("url")
        )

        followers_count = int(statistics.get("subscriberCount", 0))
        views_count = int(statistics.get("viewCount", 0))
        total_videos_count = int(statistics.get("videoCount", 0))

        metadata = {
            "uploads_playlist_id": uploads_playlist_id,
            "custom_url": snippet.get("customUrl"),
            "published_at": snippet.get("publishedAt"),
            "country": snippet.get("country"),
            "hidden_subscriber_count": statistics.get("hiddenSubscriberCount", False),
        }

        return ChannelProfile(
            platform=self.platform_name,
            platform_account_id=item["id"],
            account_name=snippet.get("title", "YouTube Channel"),
            account_handle=snippet.get("customUrl"),
            avatar_url=avatar_url,
            followers_count=followers_count,
            views_count=views_count,
            total_videos_count=total_videos_count,
            metadata_json=metadata,
        )

    async def fetch_posts(
        self,
        account_id: str,
        limit: int = 50,
        since: Optional[datetime] = None,
        access_token: Optional[str] = None,
    ) -> List[PlatformPost]:
        """Fetch channel's uploaded videos via playlistItems and enrich with video statistics."""
        # Step 1: Ensure we have the uploads playlist ID
        channel = await self.get_channel_profile(account_id, access_token=access_token)
        uploads_playlist_id = channel.metadata_json.get("uploads_playlist_id")
        if not uploads_playlist_id:
            return []

        # Step 2: Fetch playlist items (1 quota unit per call)
        max_results = min(max(limit, 1), 50)
        playlist_params = {
            "part": "snippet,contentDetails",
            "playlistId": uploads_playlist_id,
            "maxResults": max_results,
        }

        playlist_data = await self._make_request(
            "/playlistItems",
            params=playlist_params,
            access_token=access_token,
        )
        items = playlist_data.get("items", [])
        if not items:
            return []

        # Step 3: Extract video IDs and filter by 'since' if provided
        video_ids: List[str] = []
        raw_items_map: Dict[str, Dict[str, Any]] = {}

        for item in items:
            snippet = item.get("snippet", {})
            video_id = item.get("contentDetails", {}).get("videoId") or snippet.get("resourceId", {}).get("videoId")
            if not video_id:
                continue

            pub_str = snippet.get("publishedAt")
            if pub_str and since:
                try:
                    pub_dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                    if pub_dt < since:
                        continue
                except ValueError:
                    pass

            video_ids.append(video_id)
            raw_items_map[video_id] = item

        if not video_ids:
            return []

        # Step 4: Batch fetch video details & statistics (1 quota unit for up to 50 videos)
        videos_params = {
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(video_ids[:50]),
        }
        videos_data = await self._make_request(
            "/videos",
            params=videos_params,
            access_token=access_token,
        )

        posts: List[PlatformPost] = []
        for vid in videos_data.get("items", []):
            vid_id = vid["id"]
            snippet = vid.get("snippet", {})
            statistics = vid.get("statistics", {})
            content_details = vid.get("contentDetails", {})

            thumbnails = snippet.get("thumbnails", {})
            thumb_url = (
                thumbnails.get("maxres", {}).get("url")
                or thumbnails.get("standard", {}).get("url")
                or thumbnails.get("high", {}).get("url")
                or thumbnails.get("default", {}).get("url")
            )

            pub_str = snippet.get("publishedAt")
            published_at = (
                datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                if pub_str
                else datetime.now(timezone.utc)
            )

            duration = content_details.get("duration")
            # Determine post type: video or short
            post_type = "short" if duration and ("PT1M" in duration or "PT0M" in duration or "PT" in duration and "M" not in duration) else "video"

            metadata = {
                "duration": duration,
                "tags": snippet.get("tags", []),
                "categoryId": snippet.get("categoryId"),
                "views_count": int(statistics.get("viewCount", 0)),
                "likes_count": int(statistics.get("likeCount", 0)),
                "comments_count": int(statistics.get("commentCount", 0)),
            }

            posts.append(
                PlatformPost(
                    platform=self.platform_name,
                    platform_post_id=vid_id,
                    platform_account_id=channel.platform_account_id,
                    post_type=post_type,
                    title=snippet.get("title"),
                    content=snippet.get("description"),
                    url=f"https://www.youtube.com/watch?v={vid_id}",
                    thumbnail_url=thumb_url,
                    published_at=published_at,
                    metadata_json=metadata,
                )
            )

        return posts

    async def fetch_post_metrics(
        self,
        post_id: str,
        access_token: Optional[str] = None,
    ) -> PostMetrics:
        """Fetch current statistics (views, likes, comments) for a specific video."""
        params = {
            "part": "statistics",
            "id": post_id,
        }
        data = await self._make_request("/videos", params=params, access_token=access_token)
        items = data.get("items", [])
        if not items:
            raise ConnectorNotFoundError(
                f"YouTube video '{post_id}' not found",
                platform=self.platform_name,
            )

        stats = items[0].get("statistics", {})
        views = int(stats.get("viewCount", 0))
        likes = int(stats.get("likeCount", 0))
        comments = int(stats.get("commentCount", 0))

        # Calculate standard engagement rate: (likes + comments) / views * 100
        engagement_rate = ((likes + comments) / views * 100.0) if views > 0 else 0.0

        return PostMetrics(
            platform_post_id=post_id,
            views_count=views,
            likes_count=likes,
            comments_count=comments,
            shares_count=0,  # YouTube public API does not expose video share counts
            saves_count=0,
            engagement_rate=round(engagement_rate, 4),
            watch_time_minutes=0.0,
            captured_at=datetime.now(timezone.utc),
        )

    async def fetch_comments(
        self,
        post_id: str,
        limit: int = 50,
        access_token: Optional[str] = None,
    ) -> List[PlatformComment]:
        """Fetch top-level comment threads for a video."""
        max_results = min(max(limit, 1), 100)
        params = {
            "part": "snippet",
            "videoId": post_id,
            "maxResults": max_results,
            "textFormat": "plainText",
            "order": "relevance",
        }

        try:
            data = await self._make_request("/commentThreads", params=params, access_token=access_token)
        except ConnectorAPIError as e:
            # YouTube returns 403 when comments are disabled on a video
            if e.status_code == 403 and "commentsDisabled" in str(e):
                logger.info(f"Comments are disabled on video {post_id}")
                return []
            raise

        items = data.get("items", [])
        comments: List[PlatformComment] = []

        for item in items:
            top_level = item.get("snippet", {}).get("topLevelComment", {})
            c_snippet = top_level.get("snippet", {})
            c_id = top_level.get("id") or item.get("id")

            pub_str = c_snippet.get("publishedAt")
            published_at = (
                datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                if pub_str
                else datetime.now(timezone.utc)
            )

            comments.append(
                PlatformComment(
                    comment_id=c_id,
                    platform_post_id=post_id,
                    author_name=c_snippet.get("authorDisplayName", "Anonymous"),
                    author_avatar_url=c_snippet.get("authorProfileImageUrl"),
                    author_channel_url=c_snippet.get("authorChannelUrl"),
                    content=c_snippet.get("textDisplay", ""),
                    likes_count=int(c_snippet.get("likeCount", 0)),
                    published_at=published_at,
                    reply_count=int(item.get("snippet", {}).get("totalReplyCount", 0)),
                )
            )

        return comments

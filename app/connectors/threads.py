"""Official Threads API Connector implementing BaseSocialConnector.

Handles Threads OAuth2 consent flow, short-to-long-lived token lifecycle,
profile metadata and account-level insights (views, likes, replies, reposts, quotes),
threads ingestion, and media insights.
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
    ConnectorRateLimitError,
    OAuthTokenResponse,
    PlatformComment,
    PlatformPost,
    PostMetrics,
)
from app.core.config import settings

logger = logging.getLogger(__name__)


class ThreadsConnector(BaseSocialConnector):
    """Connector for the Official Threads API (graph.threads.net/v1.0)."""

    platform_name: str = "threads"

    THREADS_AUTH_BASE_URL = "https://threads.net/oauth/authorize"
    THREADS_TOKEN_URL = "https://graph.threads.net/oauth/access_token"
    THREADS_EXCHANGE_URL = "https://graph.threads.net/access_token"
    THREADS_REFRESH_URL = "https://graph.threads.net/refresh_access_token"
    THREADS_API_BASE_URL = "https://graph.threads.net/v1.0"

    DEFAULT_SCOPES = [
        "threads_basic",
        "threads_content_publish",
        "threads_read_replies",
        "threads_manage_insights",
    ]

    def __init__(
        self,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
    ):
        # Fall back to THREADS_* or META_*
        self.app_id = app_id or getattr(settings, "THREADS_APP_ID", None) or settings.META_APP_ID
        self.app_secret = app_secret or getattr(settings, "THREADS_APP_SECRET", None) or settings.META_APP_SECRET
        self.redirect_uri = redirect_uri or getattr(settings, "THREADS_REDIRECT_URI", "http://127.0.0.1:5032/api/v1/platforms/threads/callback")
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

    def get_authorization_url(self, state: str, redirect_uri: Optional[str] = None) -> str:
        """Generate Threads OAuth2 authorization consent URL."""
        if not self.app_id:
            raise ConnectorAuthError(
                "Threads app_id is not configured",
                platform=self.platform_name,
            )

        params = {
            "client_id": self.app_id,
            "redirect_uri": redirect_uri or self.redirect_uri,
            "scope": ",".join(self.DEFAULT_SCOPES),
            "response_type": "code",
            "state": state,
        }
        return f"{self.THREADS_AUTH_BASE_URL}?{urlencode(params)}"

    async def authenticate(self, auth_code: str, redirect_uri: Optional[str] = None) -> OAuthTokenResponse:
        """Exchange auth code for short-lived token and upgrade to 60-day long-lived token."""
        if not self.app_id or not self.app_secret:
            raise ConnectorAuthError(
                "Threads app_id or app_secret is not configured",
                platform=self.platform_name,
            )

        payload = {
            "client_id": self.app_id,
            "client_secret": self.app_secret,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri or self.redirect_uri,
            "code": auth_code,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(self.THREADS_TOKEN_URL, data=payload)
                data = response.json()

                if response.status_code != 200 or "error" in data:
                    err_msg = data.get("error_message") or data.get("error") or "OAuth code exchange failed"
                    raise ConnectorAuthError(
                        f"Threads OAuth exchange failed ({response.status_code}): {err_msg}",
                        platform=self.platform_name,
                    )

                short_lived_token = data["access_token"]
                user_id = data.get("user_id")

            # Upgrade to long-lived (60 days) token
            long_lived_response = await self._exchange_for_long_lived_token(short_lived_token)
            if user_id and long_lived_response.raw_response is not None:
                long_lived_response.raw_response["user_id"] = user_id

            return long_lived_response

        except (ConnectorAuthError, ConnectorAPIError):
            raise
        except httpx.RequestError as exc:
            raise ConnectorAuthError(
                f"Network error during Threads authentication: {str(exc)}",
                platform=self.platform_name,
                original_error=exc,
            )

    async def _exchange_for_long_lived_token(self, short_lived_token: str) -> OAuthTokenResponse:
        """Exchange short-lived token for 60-day long-lived token."""
        params = {
            "grant_type": "th_exchange_token",
            "client_secret": self.app_secret,
            "access_token": short_lived_token,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(self.THREADS_EXCHANGE_URL, params=params)
                data = response.json()

                if response.status_code != 200 or "error" in data:
                    err_msg = data.get("error_message") or data.get("error") or "Failed to exchange for long-lived token"
                    logger.warning(f"Could not exchange Threads long-lived token: {err_msg}. Using short-lived token.")
                    return OAuthTokenResponse(
                        access_token=short_lived_token,
                        token_type="Bearer",
                        expires_in=3600,
                    )

                return OAuthTokenResponse(
                    access_token=data["access_token"],
                    token_type=data.get("token_type", "Bearer"),
                    expires_in=data.get("expires_in", 60 * 24 * 3600),
                    raw_response=data,
                )
        except httpx.RequestError as exc:
            logger.warning(f"Network error getting Threads long-lived token: {exc}. Using short-lived token.")
            return OAuthTokenResponse(
                access_token=short_lived_token,
                token_type="Bearer",
                expires_in=3600,
            )

    async def refresh_token(self, refresh_token: str) -> OAuthTokenResponse:
        """Refresh a long-lived Threads token (valid for another 60 days)."""
        params = {
            "grant_type": "th_refresh_token",
            "access_token": refresh_token,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(self.THREADS_REFRESH_URL, params=params)
                data = response.json()

                if response.status_code != 200 or "error" in data:
                    err_msg = data.get("error_message") or data.get("error") or "Failed to refresh token"
                    raise ConnectorAuthError(
                        f"Threads token refresh failed: {err_msg}",
                        platform=self.platform_name,
                    )

                return OAuthTokenResponse(
                    access_token=data["access_token"],
                    token_type=data.get("token_type", "Bearer"),
                    expires_in=data.get("expires_in", 60 * 24 * 3600),
                    raw_response=data,
                )
        except httpx.RequestError as exc:
            raise ConnectorAuthError(
                f"Network error refreshing Threads token: {str(exc)}",
                platform=self.platform_name,
                original_error=exc,
            )

    async def get_channel_profile(
        self,
        account_id: str = "me",
        access_token: Optional[str] = None,
    ) -> ChannelProfile:
        """Fetch Threads user profile and account-level insights."""
        endpoint = f"/{account_id}" if account_id != "me" else "/me"
        fields = "id,username,name,threads_profile_picture_url,threads_biography"

        data = await self._make_request(
            endpoint=endpoint,
            params={"fields": fields},
            access_token=access_token,
        )

        user_id = str(data.get("id", account_id))
        username = data.get("username", "")
        name = data.get("name") or username
        avatar_url = data.get("threads_profile_picture_url")
        biography = data.get("threads_biography")

        # Fetch Threads user insights: views, likes, replies, reposts, quotes, followers_count
        followers_count = 0
        total_views = 0
        metadata_insights: Dict[str, Any] = {}

        try:
            insights_endpoint = f"/{user_id}/threads_insights"
            insights_params = {
                "metric": "views,likes,replies,reposts,quotes,followers_count",
            }
            insights_data = await self._make_request(
                endpoint=insights_endpoint,
                params=insights_params,
                access_token=access_token,
            )

            for item in insights_data.get("data", []):
                metric_name = item.get("name")
                total_value = item.get("total_value", {})
                val = total_value.get("value", 0) if isinstance(total_value, dict) else 0

                if metric_name == "followers_count":
                    followers_count = int(val)
                elif metric_name == "views":
                    total_views = int(val)
                
                metadata_insights[metric_name] = val
        except Exception as exc:
            logger.debug(f"Could not fetch Threads user insights for {user_id}: {exc}")

        return ChannelProfile(
            platform=self.platform_name,
            platform_account_id=user_id,
            account_name=name,
            account_handle=f"@{username}" if username else None,
            avatar_url=avatar_url,
            followers_count=followers_count,
            views_count=total_views,
            total_videos_count=0,
            metadata_json={
                "biography": biography,
                "insights": metadata_insights,
            },
        )

    async def fetch_posts(
        self,
        account_id: str = "me",
        limit: int = 50,
        since: Optional[datetime] = None,
        access_token: Optional[str] = None,
    ) -> List[PlatformPost]:
        """Fetch recent threads published by the user."""
        endpoint = f"/{account_id}/threads" if account_id != "me" else "/me/threads"
        fields = "id,media_product_type,media_type,text,permalink,timestamp,shortcode,thumbnail_url,media_url"
        params = {
            "fields": fields,
            "limit": min(limit, 100),
        }
        if since:
            params["since"] = int(since.timestamp())

        data = await self._make_request(
            endpoint=endpoint,
            params=params,
            access_token=access_token,
        )

        posts: List[PlatformPost] = []
        raw_items = data.get("data", [])

        for item in raw_items:
            thread_id = item.get("id")
            if not thread_id:
                continue

            text = item.get("text") or ""
            title = text.split("\n")[0][:120] if text else None
            published_at = self._parse_meta_datetime(item.get("timestamp"))

            thumbnail = item.get("thumbnail_url") or item.get("media_url")

            post = PlatformPost(
                platform=self.platform_name,
                platform_post_id=thread_id,
                platform_account_id=account_id,
                post_type="thread",
                title=title,
                content=text,
                url=item.get("permalink"),
                thumbnail_url=thumbnail,
                published_at=published_at,
                metadata_json={
                    "shortcode": item.get("shortcode"),
                    "media_type": item.get("media_type"),
                    "media_product_type": item.get("media_product_type"),
                },
            )
            posts.append(post)

        return posts

    async def fetch_post_metrics(
        self,
        post_id: str,
        access_token: Optional[str] = None,
    ) -> PostMetrics:
        """Fetch views, likes, replies, reposts, and quotes for a specific thread."""
        endpoint = f"/{post_id}/insights"
        params = {"metric": "views,likes,replies,reposts,quotes"}

        views_count = 0
        likes_count = 0
        replies_count = 0
        reposts_count = 0

        try:
            data = await self._make_request(
                endpoint=endpoint,
                params=params,
                access_token=access_token,
            )

            for metric in data.get("data", []):
                name = metric.get("name")
                values = metric.get("values", [])
                val = 0
                if values and isinstance(values, list):
                    val = values[0].get("value", 0)

                if name == "views":
                    views_count = int(val)
                elif name == "likes":
                    likes_count = int(val)
                elif name == "replies":
                    replies_count = int(val)
                elif name in ("reposts", "quotes"):
                    reposts_count += int(val)
        except Exception as exc:
            logger.debug(f"Could not fetch insights for thread {post_id}: {exc}")

        # Compute engagement rate
        total_interactions = likes_count + replies_count + reposts_count
        er = (total_interactions / views_count * 100.0) if views_count > 0 else 0.0

        return PostMetrics(
            platform_post_id=post_id,
            views_count=views_count,
            likes_count=likes_count,
            comments_count=replies_count,
            shares_count=reposts_count,
            saves_count=0,
            engagement_rate=round(er, 2),
            watch_time_minutes=0.0,
            captured_at=datetime.now(timezone.utc),
        )

    async def fetch_comments(
        self,
        post_id: str,
        limit: int = 50,
        access_token: Optional[str] = None,
    ) -> List[PlatformComment]:
        """Fetch replies for a specific thread."""
        endpoint = f"/{post_id}/replies"
        fields = "id,text,timestamp,username,permalink"
        params = {
            "fields": fields,
            "limit": min(limit, 100),
        }

        try:
            data = await self._make_request(
                endpoint=endpoint,
                params=params,
                access_token=access_token,
            )
        except Exception:
            # If replies endpoint not available or supported for this thread
            return []

        comments: List[PlatformComment] = []
        raw_items = data.get("data", [])

        for item in raw_items:
            cid = item.get("id")
            if not cid:
                continue

            username = item.get("username", "threads_user")
            published_at = self._parse_meta_datetime(item.get("timestamp"))

            comment = PlatformComment(
                comment_id=cid,
                platform_post_id=post_id,
                author_name=username,
                author_avatar_url=None,
                author_channel_url=f"https://threads.net/@{username}" if username else None,
                content=item.get("text", ""),
                likes_count=0,
                published_at=published_at,
                reply_count=0,
            )
            comments.append(comment)

        return comments

    async def _make_request(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        access_token: Optional[str] = None,
        method: str = "GET",
    ) -> Dict[str, Any]:
        """Make HTTP request to Threads Graph API with backoff retry."""
        cleaned_endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        url = f"{self.THREADS_API_BASE_URL}{cleaned_endpoint}"
        query_params = dict(params or {})

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
                        response = await client.post(url, params=query_params, headers=headers)
                    else:
                        response = await client.get(url, params=query_params, headers=headers)

                    status = response.status_code

                    if status in (429, 500, 502, 503, 504):
                        if attempt < self.max_retries:
                            delay = self.backoff_factor * (2 ** attempt)
                            await asyncio.sleep(delay)
                            continue
                        elif status == 429:
                            raise ConnectorRateLimitError(
                                "Threads API rate limit reached",
                                platform=self.platform_name,
                            )
                        else:
                            raise ConnectorAPIError(
                                f"Threads API server error: HTTP {status}",
                                platform=self.platform_name,
                                status_code=status,
                            )

                    data = response.json()

                    if "error" in data:
                        err = data["error"]
                        code = err.get("code")
                        msg = err.get("message", "Threads API error")

                        if code in (190, 102) or "token" in msg.lower():
                            raise ConnectorAuthError(f"Threads auth error: {msg}", platform=self.platform_name)
                        if code in (4, 17, 32, 613) or "rate limit" in msg.lower():
                            raise ConnectorRateLimitError(f"Threads rate limit: {msg}", platform=self.platform_name)
                        if code in (100, 803) and ("not exist" in msg.lower() or "not found" in msg.lower()):
                            raise ConnectorNotFoundError(f"Threads not found: {msg}", platform=self.platform_name)

                        raise ConnectorAPIError(f"Threads API error ({code}): {msg}", platform=self.platform_name, status_code=status)

                    return data

            except (ConnectorAuthError, ConnectorRateLimitError, ConnectorNotFoundError, ConnectorAPIError):
                raise
            except httpx.RequestError as exc:
                last_exception = exc
                if attempt < self.max_retries:
                    delay = self.backoff_factor * (2 ** attempt)
                    await asyncio.sleep(delay)
                else:
                    raise ConnectorAPIError(
                        f"Network failure connecting to Threads API: {str(exc)}",
                        platform=self.platform_name,
                        original_error=exc,
                    )

        if last_exception:
            raise ConnectorAPIError(
                f"Threads request failed: {str(last_exception)}",
                platform=self.platform_name,
                original_error=last_exception,
            )

        return {}

    def _parse_meta_datetime(self, dt_str: Optional[str]) -> datetime:
        """Parse ISO timestamp."""
        if not dt_str:
            return datetime.now(timezone.utc)
        try:
            if "+0000" in dt_str:
                dt_str = dt_str.replace("+0000", "+00:00")
            elif dt_str.endswith("Z"):
                dt_str = dt_str.replace("Z", "+00:00")
            return datetime.fromisoformat(dt_str)
        except Exception:
            return datetime.now(timezone.utc)

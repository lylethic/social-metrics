"""Facebook Graph API Connector implementing BaseSocialConnector.

Handles Facebook Pages profile metadata, page-level insights, posts,
post metrics (reactions, comments, shares), and comment threads.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.connectors.base import (
    BaseSocialConnector,
    ChannelProfile,
    ConnectorAPIError,
    ConnectorAuthError,
    OAuthTokenResponse,
    PlatformComment,
    PlatformPost,
    PostMetrics,
)
from app.connectors.meta_base import MetaBaseConnector
from app.core.config import settings

logger = logging.getLogger(__name__)


class FacebookConnector(BaseSocialConnector):
    """Connector for Facebook Graph API v20.0+."""

    platform_name: str = "facebook"

    FACEBOOK_SCOPES = [
        "pages_show_list",
        "pages_read_engagement",
        "pages_read_user_content",
        "read_insights",
        "public_profile",
    ]

    def __init__(
        self,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        api_version: Optional[str] = None,
        meta_base: Optional[MetaBaseConnector] = None,
    ):
        self.app_id = app_id or settings.META_APP_ID
        self.app_secret = app_secret or settings.META_APP_SECRET
        self.redirect_uri = redirect_uri or settings.META_REDIRECT_URI
        self.api_version = api_version or getattr(settings, "META_API_VERSION", "v20.0")

        self.meta_base = meta_base or MetaBaseConnector(
            app_id=self.app_id,
            app_secret=self.app_secret,
            redirect_uri=self.redirect_uri,
            api_version=self.api_version,
        )

    def get_authorization_url(self, state: str, redirect_uri: Optional[str] = None) -> str:
        """Generate Meta OAuth consent URL requesting Facebook Page permissions."""
        return self.meta_base.get_authorization_url(
            state=state,
            redirect_uri=redirect_uri or self.redirect_uri,
            scopes=self.FACEBOOK_SCOPES,
        )

    async def authenticate(self, auth_code: str, redirect_uri: Optional[str] = None) -> OAuthTokenResponse:
        """Exchange auth code for short-lived token and auto-upgrade to 60-day long-lived token."""
        short_lived = await self.meta_base.exchange_code_for_short_lived_token(
            auth_code=auth_code,
            redirect_uri=redirect_uri or self.redirect_uri,
        )

        try:
            # Upgrade to long-lived User Access Token (60 days)
            long_lived = await self.meta_base.exchange_for_long_lived_token(short_lived.access_token)
            return long_lived
        except Exception as exc:
            logger.warning(f"Failed to upgrade Facebook short-lived token to long-lived: {exc}. Returning short-lived token.")
            return short_lived

    async def refresh_token(self, refresh_token: str) -> OAuthTokenResponse:
        """Refresh a long-lived user token before expiration using fb_exchange_token."""
        return await self.meta_base.exchange_for_long_lived_token(short_lived_token=refresh_token)

    async def get_channel_profile(
        self,
        account_id: str,
        access_token: Optional[str] = None,
    ) -> ChannelProfile:
        """Fetch Facebook Page profile information and page insights."""
        fields = "id,name,username,about,fan_count,followers_count,picture{url},link"
        endpoint = f"/{account_id}"
        
        data = await self.meta_base.make_graph_request(
            endpoint=endpoint,
            params={"fields": fields},
            access_token=access_token,
            platform_name=self.platform_name,
        )

        page_id = str(data.get("id", account_id))
        page_name = data.get("name", "")
        username = data.get("username")
        followers = data.get("followers_count") or data.get("fan_count") or 0
        
        # Extract avatar
        avatar_url = None
        picture_data = data.get("picture", {})
        if isinstance(picture_data, dict):
            avatar_url = picture_data.get("data", {}).get("url")

        # Attempt to fetch page insights (views, impressions)
        views_count = 0
        try:
            insights_data = await self.meta_base.make_graph_request(
                endpoint=f"/{page_id}/insights",
                params={"metric": "page_impressions,page_views_total", "period": "day"},
                access_token=access_token,
                platform_name=self.platform_name,
            )
            for item in insights_data.get("data", []):
                metric_name = item.get("name")
                values = item.get("values", [])
                if values and isinstance(values, list):
                    latest_val = values[-1].get("value", 0)
                    if isinstance(latest_val, (int, float)):
                        views_count += int(latest_val)
        except Exception as exc:
            logger.debug(f"Could not fetch Facebook page insights for {page_id}: {exc}")

        return ChannelProfile(
            platform=self.platform_name,
            platform_account_id=page_id,
            account_name=page_name,
            account_handle=f"@{username}" if username else None,
            avatar_url=avatar_url,
            followers_count=followers,
            views_count=views_count,
            total_videos_count=0,
            metadata_json={
                "about": data.get("about"),
                "link": data.get("link"),
                "fan_count": data.get("fan_count", 0),
            },
        )

    async def fetch_posts(
        self,
        account_id: str,
        limit: int = 50,
        since: Optional[datetime] = None,
        access_token: Optional[str] = None,
    ) -> List[PlatformPost]:
        """Fetch recent posts published by the Facebook Page."""
        endpoint = f"/{account_id}/posts"
        fields = "id,message,story,created_time,permalink_url,full_picture,shares,reactions.summary(true),comments.summary(true)"
        params = {
            "fields": fields,
            "limit": min(limit, 100),
        }
        if since:
            params["since"] = int(since.timestamp())

        data = await self.meta_base.make_graph_request(
            endpoint=endpoint,
            params=params,
            access_token=access_token,
            platform_name=self.platform_name,
        )

        posts: List[PlatformPost] = []
        raw_items = data.get("data", [])

        for item in raw_items:
            post_id = item.get("id")
            if not post_id:
                continue

            created_time_str = item.get("created_time")
            published_at = self._parse_meta_datetime(created_time_str)

            message = item.get("message") or item.get("story") or ""
            # Truncate title from first line of message
            title = message.split("\n")[0][:120] if message else None

            # Determine post type
            has_picture = bool(item.get("full_picture"))
            post_type = "photo" if has_picture else "text"

            post = PlatformPost(
                platform=self.platform_name,
                platform_post_id=post_id,
                platform_account_id=account_id,
                post_type=post_type,
                title=title,
                content=message,
                url=item.get("permalink_url"),
                thumbnail_url=item.get("full_picture"),
                published_at=published_at,
                metadata_json={
                    "story": item.get("story"),
                },
            )
            posts.append(post)

        return posts

    async def fetch_post_metrics(
        self,
        post_id: str,
        access_token: Optional[str] = None,
    ) -> PostMetrics:
        """Fetch reactions, comments, shares, and impressions for an individual Facebook post."""
        fields = "id,shares,reactions.summary(true),comments.summary(true)"
        data = await self.meta_base.make_graph_request(
            endpoint=f"/{post_id}",
            params={"fields": fields},
            access_token=access_token,
            platform_name=self.platform_name,
        )

        reactions_summary = data.get("reactions", {}).get("summary", {})
        likes_count = reactions_summary.get("total_count", 0)

        comments_summary = data.get("comments", {}).get("summary", {})
        comments_count = comments_summary.get("total_count", 0)

        shares_info = data.get("shares", {})
        shares_count = shares_info.get("count", 0) if isinstance(shares_info, dict) else 0

        # Attempt to get post impressions from post insights
        views_count = 0
        try:
            insights = await self.meta_base.make_graph_request(
                endpoint=f"/{post_id}/insights",
                params={"metric": "post_impressions"},
                access_token=access_token,
                platform_name=self.platform_name,
            )
            for item in insights.get("data", []):
                if item.get("name") == "post_impressions":
                    values = item.get("values", [])
                    if values:
                        views_count = values[-1].get("value", 0)
        except Exception:
            # Post impressions might require specific page tokens or not be available for all posts
            pass

        # Calculate engagement rate
        total_engagements = likes_count + comments_count + shares_count
        er = (total_engagements / views_count * 100.0) if views_count > 0 else 0.0

        return PostMetrics(
            platform_post_id=post_id,
            views_count=views_count,
            likes_count=likes_count,
            comments_count=comments_count,
            shares_count=shares_count,
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
        """Fetch comments for a given Facebook post."""
        endpoint = f"/{post_id}/comments"
        fields = "id,message,created_time,from{id,name,picture},like_count,comment_count"
        params = {
            "fields": fields,
            "limit": min(limit, 100),
            "summary": "true",
        }

        data = await self.meta_base.make_graph_request(
            endpoint=endpoint,
            params=params,
            access_token=access_token,
            platform_name=self.platform_name,
        )

        comments: List[PlatformComment] = []
        raw_items = data.get("data", [])

        for item in raw_items:
            cid = item.get("id")
            if not cid:
                continue

            author_info = item.get("from", {}) or {}
            author_name = author_info.get("name", "Facebook User")
            avatar_url = None
            pic_obj = author_info.get("picture", {})
            if isinstance(pic_obj, dict):
                avatar_url = pic_obj.get("data", {}).get("url")

            published_at = self._parse_meta_datetime(item.get("created_time"))

            comment = PlatformComment(
                comment_id=cid,
                platform_post_id=post_id,
                author_name=author_name,
                author_avatar_url=avatar_url,
                author_channel_url=None,
                content=item.get("message", ""),
                likes_count=item.get("like_count", 0),
                published_at=published_at,
                reply_count=item.get("comment_count", 0),
            )
            comments.append(comment)

        return comments

    def _parse_meta_datetime(self, dt_str: Optional[str]) -> datetime:
        """Parse Meta ISO 8601 timestamp string (e.g., 2024-05-01T12:00:00+0000 or Z)."""
        if not dt_str:
            return datetime.now(timezone.utc)
        try:
            # Handle +0000 format
            if "+0000" in dt_str:
                dt_str = dt_str.replace("+0000", "+00:00")
            elif dt_str.endswith("Z"):
                dt_str = dt_str.replace("Z", "+00:00")
            return datetime.fromisoformat(dt_str)
        except Exception:
            return datetime.now(timezone.utc)

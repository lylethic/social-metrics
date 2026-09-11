"""Instagram Graph API Connector implementing BaseSocialConnector.

Handles Instagram Professional / Business account profile metrics, media (reels,
videos, photos), post metrics (reach, impressions, saved, engagement), and comments.
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


class InstagramConnector(BaseSocialConnector):
    """Connector for Instagram Graph API (via Meta Graph API v20.0+)."""

    platform_name: str = "instagram"

    INSTAGRAM_SCOPES = [
        "instagram_basic",
        "instagram_manage_insights",
        "pages_show_list",
        "pages_read_engagement",
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
        """Generate Meta OAuth consent URL requesting Instagram Business permissions."""
        return self.meta_base.get_authorization_url(
            state=state,
            redirect_uri=redirect_uri or self.redirect_uri,
            scopes=self.INSTAGRAM_SCOPES,
        )

    async def authenticate(self, auth_code: str, redirect_uri: Optional[str] = None) -> OAuthTokenResponse:
        """Exchange auth code for short-lived token and upgrade to 60-day long-lived token."""
        short_lived = await self.meta_base.exchange_code_for_short_lived_token(
            auth_code=auth_code,
            redirect_uri=redirect_uri or self.redirect_uri,
        )

        try:
            long_lived = await self.meta_base.exchange_for_long_lived_token(short_lived.access_token)
            return long_lived
        except Exception as exc:
            logger.warning(f"Failed to upgrade Instagram token: {exc}. Returning short-lived token.")
            return short_lived

    async def refresh_token(self, refresh_token: str) -> OAuthTokenResponse:
        """Refresh long-lived access token before expiration."""
        return await self.meta_base.exchange_for_long_lived_token(short_lived_token=refresh_token)

    async def get_instagram_business_account_id(self, page_id: str, access_token: str) -> Optional[str]:
        """Discover linked Instagram Business/Creator Account ID from a Facebook Page."""
        data = await self.meta_base.make_graph_request(
            endpoint=f"/{page_id}",
            params={"fields": "instagram_business_account{id,username,name}"},
            access_token=access_token,
            platform_name=self.platform_name,
        )
        ig_obj = data.get("instagram_business_account")
        if isinstance(ig_obj, dict):
            return ig_obj.get("id")
        return None

    async def get_channel_profile(
        self,
        account_id: str,
        access_token: Optional[str] = None,
    ) -> ChannelProfile:
        """Fetch Instagram Business Profile metadata and profile insights."""
        fields = "id,username,name,biography,profile_picture_url,followers_count,follows_count,media_count,website"
        data = await self.meta_base.make_graph_request(
            endpoint=f"/{account_id}",
            params={"fields": fields},
            access_token=access_token,
            platform_name=self.platform_name,
        )

        ig_id = str(data.get("id", account_id))
        username = data.get("username", "")
        name = data.get("name") or username
        followers = data.get("followers_count", 0)
        media_count = data.get("media_count", 0)
        avatar_url = data.get("profile_picture_url")

        # Fetch profile insights (impressions, reach, profile_views)
        views_count = 0
        try:
            insights_data = await self.meta_base.make_graph_request(
                endpoint=f"/{ig_id}/insights",
                params={"metric": "impressions,reach,profile_views", "period": "day"},
                access_token=access_token,
                platform_name=self.platform_name,
            )
            for item in insights_data.get("data", []):
                metric_name = item.get("name")
                if metric_name in ("impressions", "reach"):
                    values = item.get("values", [])
                    if values and isinstance(values, list):
                        latest_val = values[-1].get("value", 0)
                        if isinstance(latest_val, (int, float)):
                            views_count += int(latest_val)
        except Exception as exc:
            logger.debug(f"Could not fetch Instagram profile insights for {ig_id}: {exc}")

        return ChannelProfile(
            platform=self.platform_name,
            platform_account_id=ig_id,
            account_name=name,
            account_handle=f"@{username}" if username else None,
            avatar_url=avatar_url,
            followers_count=followers,
            views_count=views_count,
            total_videos_count=media_count,
            metadata_json={
                "biography": data.get("biography"),
                "website": data.get("website"),
                "follows_count": data.get("follows_count", 0),
            },
        )

    async def fetch_posts(
        self,
        account_id: str,
        limit: int = 50,
        since: Optional[datetime] = None,
        access_token: Optional[str] = None,
    ) -> List[PlatformPost]:
        """Fetch recent media (Reels, Videos, Photos) published by the Instagram account."""
        endpoint = f"/{account_id}/media"
        fields = "id,caption,media_type,media_product_type,media_url,thumbnail_url,permalink,timestamp,like_count,comments_count"
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
            media_id = item.get("id")
            if not media_id:
                continue

            caption = item.get("caption") or ""
            title = caption.split("\n")[0][:120] if caption else None

            # Map Instagram types to standardized post_type
            product_type = (item.get("media_product_type") or "").upper()
            media_type = (item.get("media_type") or "").upper()

            if product_type == "REELS":
                post_type = "reel"
            elif media_type == "VIDEO":
                post_type = "video"
            else:
                post_type = "photo"

            thumbnail = item.get("thumbnail_url") or item.get("media_url")
            published_at = self._parse_meta_datetime(item.get("timestamp"))

            post = PlatformPost(
                platform=self.platform_name,
                platform_post_id=media_id,
                platform_account_id=account_id,
                post_type=post_type,
                title=title,
                content=caption,
                url=item.get("permalink"),
                thumbnail_url=thumbnail,
                published_at=published_at,
                metadata_json={
                    "media_type": media_type,
                    "media_product_type": product_type,
                    "like_count": item.get("like_count", 0),
                    "comments_count": item.get("comments_count", 0),
                },
            )
            posts.append(post)

        return posts

    async def fetch_post_metrics(
        self,
        post_id: str,
        access_token: Optional[str] = None,
    ) -> PostMetrics:
        """Fetch likes, comments, impressions, reach, and saved counts for an Instagram media item."""
        media_data = await self.meta_base.make_graph_request(
            endpoint=f"/{post_id}",
            params={"fields": "id,like_count,comments_count,media_type,media_product_type"},
            access_token=access_token,
            platform_name=self.platform_name,
        )

        likes_count = media_data.get("like_count", 0)
        comments_count = media_data.get("comments_count", 0)
        saves_count = 0
        views_count = 0

        # Query media insights for reach, impressions, saved, and video_views
        media_type = (media_data.get("media_type") or "").upper()
        product_type = (media_data.get("media_product_type") or "").upper()

        if product_type == "REELS":
            metrics_param = "reach,saved,likes,comments,shares,plays"
        elif media_type == "VIDEO":
            metrics_param = "engagement,impressions,reach,saved,video_views"
        else:
            metrics_param = "engagement,impressions,reach,saved"

        shares_count = 0
        try:
            insights_data = await self.meta_base.make_graph_request(
                endpoint=f"/{post_id}/insights",
                params={"metric": metrics_param},
                access_token=access_token,
                platform_name=self.platform_name,
            )
            for metric in insights_data.get("data", []):
                m_name = metric.get("name")
                m_values = metric.get("values", [])
                val = 0
                if m_values and isinstance(m_values, list):
                    val = m_values[0].get("value", 0)

                if m_name in ("impressions", "reach", "plays", "video_views"):
                    views_count = max(views_count, int(val))
                elif m_name == "saved":
                    saves_count = int(val)
                elif m_name == "shares":
                    shares_count = int(val)
        except Exception as exc:
            logger.debug(f"Could not fetch Instagram insights for media {post_id}: {exc}")

        # Compute engagement rate
        total_engagements = likes_count + comments_count + shares_count + saves_count
        er = (total_engagements / views_count * 100.0) if views_count > 0 else 0.0

        return PostMetrics(
            platform_post_id=post_id,
            views_count=views_count,
            likes_count=likes_count,
            comments_count=comments_count,
            shares_count=shares_count,
            saves_count=saves_count,
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
        """Fetch comments on an Instagram media item."""
        endpoint = f"/{post_id}/comments"
        fields = "id,text,timestamp,username,like_count"
        params = {
            "fields": fields,
            "limit": min(limit, 100),
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

            username = item.get("username", "instagram_user")
            published_at = self._parse_meta_datetime(item.get("timestamp"))

            comment = PlatformComment(
                comment_id=cid,
                platform_post_id=post_id,
                author_name=username,
                author_avatar_url=None,
                author_channel_url=f"https://instagram.com/{username}" if username else None,
                content=item.get("text", ""),
                likes_count=item.get("like_count", 0),
                published_at=published_at,
                reply_count=0,
            )
            comments.append(comment)

        return comments

    def _parse_meta_datetime(self, dt_str: Optional[str]) -> datetime:
        """Parse Meta ISO timestamp."""
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

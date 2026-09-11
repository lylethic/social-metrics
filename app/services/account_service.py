"""Platform account service handling connection, token management, and data synchronization."""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.base import (
    BaseSocialConnector,
    ChannelProfile,
    ConnectorAuthError,
    OAuthTokenResponse,
)
from app.connectors.facebook import FacebookConnector
from app.connectors.instagram import InstagramConnector
from app.connectors.meta_base import MetaBaseConnector
from app.connectors.threads import ThreadsConnector
from app.connectors.youtube import YouTubeConnector
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
)
from app.models.metric_snapshot import MetricSnapshot
from app.models.platform_account import PlatformAccount
from app.models.post import Post

logger = logging.getLogger(__name__)


class AccountService:
    """Service handling platform account persistence, token management, and data synchronization."""

    def __init__(self):
        self.youtube_connector = YouTubeConnector()
        self.meta_base = MetaBaseConnector()
        self.facebook_connector = FacebookConnector(meta_base=self.meta_base)
        self.instagram_connector = InstagramConnector(meta_base=self.meta_base)
        self.threads_connector = ThreadsConnector()

    def get_connector(self, platform: str) -> BaseSocialConnector:
        """Retrieve appropriate connector instance for given platform name."""
        p = platform.lower()
        if p == "youtube":
            return self.youtube_connector
        elif p == "facebook":
            return self.facebook_connector
        elif p == "instagram":
            return self.instagram_connector
        elif p == "threads":
            return self.threads_connector
        raise BadRequestException(detail=f"Platform '{platform}' is not supported.")

    async def list_by_user(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        platform: Optional[str] = None,
    ) -> List[PlatformAccount]:
        """Fetch all connected social accounts for a given user."""
        query = select(PlatformAccount).where(PlatformAccount.user_id == user_id)
        if platform:
            query = query.where(PlatformAccount.platform == platform.lower())
        query = query.order_by(PlatformAccount.created_at.desc())
        result = await db.execute(query)
        return list(result.scalars().all())

    async def get_by_id(
        self,
        db: AsyncSession,
        account_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
    ) -> Optional[PlatformAccount]:
        """Fetch a specific platform account by UUID, optionally ensuring user ownership."""
        query = select(PlatformAccount).where(PlatformAccount.id == account_id)
        if user_id is not None:
            query = query.where(PlatformAccount.user_id == user_id)
        result = await db.execute(query)
        return result.scalars().first()

    async def get_by_platform_and_account_id(
        self,
        db: AsyncSession,
        platform: str,
        platform_account_id: str,
        user_id: Optional[uuid.UUID] = None,
    ) -> Optional[PlatformAccount]:
        """Fetch account by platform name and external platform ID."""
        query = select(PlatformAccount).where(
            PlatformAccount.platform == platform.lower(),
            PlatformAccount.platform_account_id == platform_account_id,
        )
        if user_id is not None:
            query = query.where(PlatformAccount.user_id == user_id)
        result = await db.execute(query)
        return result.scalars().first()

    async def connect_or_update_account(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        profile: ChannelProfile,
        tokens: Optional[OAuthTokenResponse] = None,
    ) -> PlatformAccount:
        """Create or update a connected platform account and persist its profile info."""
        existing = await self.get_by_platform_and_account_id(
            db=db,
            platform=profile.platform,
            platform_account_id=profile.platform_account_id,
        )

        # Calculate token expiration timestamp
        token_expires_at = None
        if tokens and tokens.expires_in:
            token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=tokens.expires_in)

        if existing:
            # Check ownership conflict
            if existing.user_id != user_id:
                raise ConflictException(
                    detail=f"This {profile.platform} channel is already linked to another user account."
                )

            # Update existing account
            existing.account_name = profile.account_name
            existing.account_handle = profile.account_handle
            existing.avatar_url = profile.avatar_url
            existing.metadata_json = profile.metadata_json
            existing.is_active = True

            if tokens:
                existing.access_token = tokens.access_token
                if tokens.refresh_token:
                    existing.refresh_token = tokens.refresh_token
                existing.token_expires_at = token_expires_at

            await db.flush()
            await db.refresh(existing)
            account = existing
        else:
            # Create new account
            account = PlatformAccount(
                user_id=user_id,
                platform=profile.platform.lower(),
                platform_account_id=profile.platform_account_id,
                account_name=profile.account_name,
                account_handle=profile.account_handle,
                avatar_url=profile.avatar_url,
                access_token=tokens.access_token if tokens else None,
                refresh_token=tokens.refresh_token if tokens else None,
                token_expires_at=token_expires_at,
                metadata_json=profile.metadata_json,
                is_active=True,
            )
            db.add(account)
            await db.flush()
            await db.refresh(account)

        # Create initial channel snapshot record
        channel_snapshot = MetricSnapshot(
            entity_type="channel",
            platform_account_id=account.id,
            post_id=None,
            views_count=profile.views_count,
            followers_count=profile.followers_count,
            total_videos_count=profile.total_videos_count,
            captured_at=datetime.now(timezone.utc),
        )
        db.add(channel_snapshot)
        await db.flush()

        return account

    async def delete_account(
        self,
        db: AsyncSession,
        account_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> bool:
        """Delete a platform account belonging to user."""
        account = await self.get_by_id(db, account_id, user_id=user_id)
        if not account:
            raise NotFoundException(detail="Platform account not found.")

        await db.delete(account)
        await db.flush()
        return True

    async def get_valid_token(
        self,
        db: AsyncSession,
        account: PlatformAccount,
    ) -> Optional[str]:
        """Return a valid access token, auto-refreshing if expired and refresh_token is available."""
        if not account.access_token:
            return None

        # Check if expired or about to expire in next 2 minutes
        now = datetime.now(timezone.utc)
        if account.token_expires_at:
            expires_at = account.token_expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= (now + timedelta(minutes=2)) and account.refresh_token:
                try:
                    connector = self.get_connector(account.platform)
                    new_tokens = await connector.refresh_token(account.refresh_token)
                    account.access_token = new_tokens.access_token
                    if new_tokens.refresh_token:
                        account.refresh_token = new_tokens.refresh_token
                    if new_tokens.expires_in:
                        account.token_expires_at = now + timedelta(seconds=new_tokens.expires_in)
                    await db.flush()
                    return account.access_token
                except Exception as exc:
                    logger.error(f"Failed to auto-refresh token for account {account.id}: {exc}")
                    raise ConnectorAuthError(f"Failed to refresh expired token: {exc}", platform=account.platform)

        return account.access_token

    async def sync_account_data(
        self,
        db: AsyncSession,
        account: PlatformAccount,
        limit_posts: int = 20,
    ) -> dict:
        """Sync channel profile metrics and recent posts for a connected platform account."""
        token = await self.get_valid_token(db, account)
        connector = self.get_connector(account.platform)

        # 1. Fetch current profile statistics
        profile = await connector.get_channel_profile(
            account_id=account.platform_account_id,
            access_token=token,
        )

        account.account_name = profile.account_name
        account.account_handle = profile.account_handle or account.account_handle
        account.avatar_url = profile.avatar_url or account.avatar_url
        account.metadata_json = profile.metadata_json

        # 2. Record channel snapshot
        channel_snapshot = MetricSnapshot(
            entity_type="channel",
            platform_account_id=account.id,
            views_count=profile.views_count,
            followers_count=profile.followers_count,
            total_videos_count=profile.total_videos_count,
            captured_at=datetime.now(timezone.utc),
        )
        db.add(channel_snapshot)

        # 3. Fetch recent posts/videos
        platform_posts = await connector.fetch_posts(
            account_id=account.platform_account_id,
            limit=limit_posts,
            access_token=token,
        )

        posts_synced_count = 0
        for p_data in platform_posts:
            # Check if post exists
            res = await db.execute(
                select(Post).where(
                    Post.platform_account_id == account.id,
                    Post.platform_post_id == p_data.platform_post_id,
                )
            )
            existing_post = res.scalars().first()

            if existing_post:
                existing_post.title = p_data.title
                existing_post.content = p_data.content
                existing_post.thumbnail_url = p_data.thumbnail_url
                existing_post.metadata_json = p_data.metadata_json
                post_record = existing_post
            else:
                post_record = Post(
                    platform_account_id=account.id,
                    platform_post_id=p_data.platform_post_id,
                    post_type=p_data.post_type,
                    title=p_data.title,
                    content=p_data.content,
                    url=p_data.url,
                    thumbnail_url=p_data.thumbnail_url,
                    published_at=p_data.published_at,
                    metadata_json=p_data.metadata_json,
                )
                db.add(post_record)
                await db.flush()

            # Record post metric snapshot if metadata contains statistics
            meta = p_data.metadata_json or {}
            v_views = meta.get("views_count", 0)
            v_likes = meta.get("likes_count", 0)
            v_comments = meta.get("comments_count", 0)
            er = ((v_likes + v_comments) / v_views * 100.0) if v_views > 0 else 0.0

            post_snapshot = MetricSnapshot(
                entity_type="post",
                platform_account_id=account.id,
                post_id=post_record.id,
                views_count=v_views,
                likes_count=v_likes,
                comments_count=v_comments,
                engagement_rate=round(er, 4),
                captured_at=datetime.now(timezone.utc),
            )
            db.add(post_snapshot)
            posts_synced_count += 1

        await db.flush()

        return {
            "platform_account_id": account.id,
            "platform": account.platform,
            "channel_name": account.account_name,
            "posts_synced_count": posts_synced_count,
            "followers_count": profile.followers_count,
            "views_count": profile.views_count,
            "synced_at": datetime.now(timezone.utc),
        }


account_service = AccountService()

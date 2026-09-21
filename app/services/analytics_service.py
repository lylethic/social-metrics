"""Analytics and Aggregation Service for cross-platform metrics, growth calculations, and content ranking."""

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.metric_snapshot import MetricSnapshot
from app.models.platform_account import PlatformAccount
from app.models.post import Post
from app.schemas.metric import (
    ChannelDetailResponse,
    ChannelGrowthResponse,
    GrowthMetric,
    GrowthOverviewResponse,
    InsightsSummaryResponse,
    MetricSnapshotResponse,
    PlatformBreakdownItem,
    TimeSeriesPoint,
    TimeSeriesResponse,
    TopContentResponse,
    TopPostItem,
)
from app.schemas.post import PostListResponse, PostWithMetricsResponse

logger = logging.getLogger(__name__)


def calculate_engagement_rate(
    likes: int,
    comments: int,
    shares: int = 0,
    saves: int = 0,
    views: int = 0,
) -> float:
    """
    Calculate Engagement Rate (ER):
    ER = ((Likes + Comments + Shares + Saves) / Total Views) * 100%
    Safely returns 0.0 if views <= 0.
    """
    if views <= 0:
        return 0.0
    total_interactions = likes + comments + shares + saves
    er = (total_interactions / views) * 100.0
    return round(er, 4)


def calculate_growth_rate(current: int, baseline: int, timeframe: str = "7d") -> GrowthMetric:
    """
    Calculate growth rate between baseline and current values:
    Growth = ((current - baseline) / baseline) * 100%
    """
    change = current - baseline
    if baseline > 0:
        rate = round((change / baseline) * 100.0, 2)
    elif baseline == 0 and current > 0:
        rate = 100.0
    else:
        rate = 0.0

    return GrowthMetric(
        current=current,
        baseline=baseline,
        change=change,
        growth_rate=rate,
        timeframe=timeframe,
    )


class AnalyticsService:
    """Service providing metrics aggregation, growth rates, time-series, and content ranking."""

    # -------------------------------------------------------------
    # Snapshots & Growth
    # -------------------------------------------------------------

    async def get_channel_snapshots(
        self,
        db: AsyncSession,
        account_id: uuid.UUID,
        days: int = 30,
    ) -> List[MetricSnapshot]:
        """Fetch historical snapshots for a channel over the specified number of days."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        query = (
            select(MetricSnapshot)
            .where(
                MetricSnapshot.entity_type == "channel",
                MetricSnapshot.platform_account_id == account_id,
                MetricSnapshot.captured_at >= since,
            )
            .order_by(MetricSnapshot.captured_at.asc())
        )
        result = await db.execute(query)
        return list(result.scalars().all())

    async def get_post_snapshots(
        self,
        db: AsyncSession,
        post_id: uuid.UUID,
        days: int = 30,
    ) -> List[MetricSnapshot]:
        """Fetch historical snapshots for an individual post."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        query = (
            select(MetricSnapshot)
            .where(
                MetricSnapshot.entity_type == "post",
                MetricSnapshot.post_id == post_id,
                MetricSnapshot.captured_at >= since,
            )
            .order_by(MetricSnapshot.captured_at.asc())
        )
        result = await db.execute(query)
        return list(result.scalars().all())

    async def get_latest_channel_snapshot(
        self,
        db: AsyncSession,
        account_id: uuid.UUID,
    ) -> Optional[MetricSnapshot]:
        """Retrieve the most recent metric snapshot for a channel."""
        query = (
            select(MetricSnapshot)
            .where(
                MetricSnapshot.entity_type == "channel",
                MetricSnapshot.platform_account_id == account_id,
            )
            .order_by(MetricSnapshot.captured_at.desc())
            .limit(1)
        )
        result = await db.execute(query)
        return result.scalars().first()

    async def get_channel_growth(
        self,
        db: AsyncSession,
        account: PlatformAccount,
    ) -> ChannelGrowthResponse:
        """Calculate WoW (7 days) and MoM (30 days) follower and view growth for a channel."""
        now = datetime.now(timezone.utc)
        latest_snap = await self.get_latest_channel_snapshot(db, account.id)

        curr_followers = latest_snap.followers_count if latest_snap else 0
        curr_views = latest_snap.views_count if latest_snap else 0

        # Snapshot ~7 days ago (closest snapshot captured on or before 7 days ago)
        seven_days_ago = now - timedelta(days=7)
        q_wow = (
            select(MetricSnapshot)
            .where(
                MetricSnapshot.entity_type == "channel",
                MetricSnapshot.platform_account_id == account.id,
                MetricSnapshot.captured_at <= seven_days_ago,
            )
            .order_by(MetricSnapshot.captured_at.desc())
            .limit(1)
        )
        res_wow = await db.execute(q_wow)
        snap_wow = res_wow.scalars().first()

        # Snapshot ~30 days ago
        thirty_days_ago = now - timedelta(days=30)
        q_mom = (
            select(MetricSnapshot)
            .where(
                MetricSnapshot.entity_type == "channel",
                MetricSnapshot.platform_account_id == account.id,
                MetricSnapshot.captured_at <= thirty_days_ago,
            )
            .order_by(MetricSnapshot.captured_at.desc())
            .limit(1)
        )
        res_mom = await db.execute(q_mom)
        snap_mom = res_mom.scalars().first()

        wow_baseline_followers = snap_wow.followers_count if snap_wow else curr_followers
        wow_baseline_views = snap_wow.views_count if snap_wow else curr_views

        mom_baseline_followers = snap_mom.followers_count if snap_mom else curr_followers
        mom_baseline_views = snap_mom.views_count if snap_mom else curr_views

        return ChannelGrowthResponse(
            channel_id=account.id,
            channel_name=account.account_name,
            platform=account.platform,
            followers_wow=calculate_growth_rate(curr_followers, wow_baseline_followers, timeframe="7d"),
            followers_mom=calculate_growth_rate(curr_followers, mom_baseline_followers, timeframe="30d"),
            views_wow=calculate_growth_rate(curr_views, wow_baseline_views, timeframe="7d"),
            views_mom=calculate_growth_rate(curr_views, mom_baseline_views, timeframe="30d"),
        )

    async def get_growth_overview(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        platform: Optional[str] = None,
    ) -> GrowthOverviewResponse:
        """Calculate aggregated and per-channel WoW and MoM growth rates for a user."""
        q = select(PlatformAccount).where(PlatformAccount.user_id == user_id, PlatformAccount.is_active == True)
        if platform:
            q = q.where(PlatformAccount.platform == platform.lower())
        res = await db.execute(q)
        accounts = list(res.scalars().all())

        channel_growths: List[ChannelGrowthResponse] = []
        total_curr_followers = 0
        total_wow_followers = 0
        total_mom_followers = 0

        for acc in accounts:
            cg = await self.get_channel_growth(db, acc)
            channel_growths.append(cg)
            total_curr_followers += cg.followers_wow.current
            total_wow_followers += cg.followers_wow.baseline
            total_mom_followers += cg.followers_mom.baseline

        agg_wow = calculate_growth_rate(total_curr_followers, total_wow_followers, timeframe="7d")
        agg_mom = calculate_growth_rate(total_curr_followers, total_mom_followers, timeframe="30d")

        return GrowthOverviewResponse(
            followers_wow=agg_wow,
            followers_mom=agg_mom,
            channels=channel_growths,
        )

    # -------------------------------------------------------------
    # Unified Overview & Dashboard
    # -------------------------------------------------------------

    async def get_unified_overview(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        platform: Optional[str] = None,
    ) -> InsightsSummaryResponse:
        """
        Aggregate total followers, views, interactions, and engagement rates across all user platforms.
        Also calculates platform breakdown and growth rates.
        """
        # 1. Fetch user accounts
        acc_query = select(PlatformAccount).where(
            PlatformAccount.user_id == user_id,
            PlatformAccount.is_active == True,
        )
        if platform:
            acc_query = acc_query.where(PlatformAccount.platform == platform.lower())
        acc_result = await db.execute(acc_query)
        accounts = list(acc_result.scalars().all())

        if not accounts:
            return InsightsSummaryResponse(
                total_channels=0,
                total_posts=0,
                total_followers=0,
                total_views=0,
                total_interactions=0,
                average_engagement_rate=0.0,
                platforms=[],
                growth=None,
                cached=False,
                generated_at=datetime.now(timezone.utc),
            )

        account_ids = [acc.id for acc in accounts]
        acc_platform_map = {acc.id: acc.platform for acc in accounts}

        # 2. Get latest snapshot for each channel
        total_followers = 0
        total_views_from_channels = 0
        platform_followers = defaultdict(int)
        platform_views = defaultdict(int)
        platform_acc_count = defaultdict(int)

        for acc in accounts:
            platform_acc_count[acc.platform] += 1
            latest_snap = await self.get_latest_channel_snapshot(db, acc.id)
            if latest_snap:
                total_followers += latest_snap.followers_count
                total_views_from_channels += latest_snap.views_count
                platform_followers[acc.platform] += latest_snap.followers_count
                platform_views[acc.platform] += latest_snap.views_count

        # 3. Get all posts for these accounts
        posts_query = select(Post).where(Post.platform_account_id.in_(account_ids))
        posts_result = await db.execute(posts_query)
        posts = list(posts_result.scalars().all())
        total_posts = len(posts)

        platform_posts_count = defaultdict(int)
        for p in posts:
            p_plat = acc_platform_map.get(p.platform_account_id, "unknown")
            platform_posts_count[p_plat] += 1

        # 4. Fetch latest snapshot for each post
        total_interactions = 0
        total_post_views = 0
        post_er_sum = 0.0
        post_er_count = 0
        platform_interactions = defaultdict(int)
        platform_post_views = defaultdict(int)
        platform_er_sum = defaultdict(float)
        platform_er_count = defaultdict(int)

        if posts:
            post_ids = [p.id for p in posts]
            post_to_account = {p.id: p.platform_account_id for p in posts}

            # Window function for latest post snapshot
            subq = (
                select(
                    MetricSnapshot,
                    func.row_number().over(
                        partition_by=MetricSnapshot.post_id,
                        order_by=MetricSnapshot.captured_at.desc(),
                    ).label("rn"),
                )
                .where(
                    MetricSnapshot.entity_type == "post",
                    MetricSnapshot.post_id.in_(post_ids),
                )
                .subquery()
            )

            q_snaps = select(MetricSnapshot).join(subq, MetricSnapshot.id == subq.c.id).where(subq.c.rn == 1)
            snap_res = await db.execute(q_snaps)
            latest_post_snaps = list(snap_res.scalars().all())

            for s in latest_post_snaps:
                interactions = s.likes_count + s.comments_count + s.shares_count + s.saves_count
                total_interactions += interactions
                total_post_views += s.views_count

                er = calculate_engagement_rate(
                    likes=s.likes_count,
                    comments=s.comments_count,
                    shares=s.shares_count,
                    saves=s.saves_count,
                    views=s.views_count,
                )
                post_er_sum += er
                post_er_count += 1

                acc_id = post_to_account.get(s.post_id)
                plat = acc_platform_map.get(acc_id, "unknown")
                platform_interactions[plat] += interactions
                platform_post_views[plat] += s.views_count
                platform_er_sum[plat] += er
                platform_er_count[plat] += 1

        # Overall ER: use aggregate interactions / aggregate views if views available, or avg ER of posts
        if total_post_views > 0:
            avg_er = round((total_interactions / total_post_views) * 100.0, 4)
        elif post_er_count > 0:
            avg_er = round(post_er_sum / post_er_count, 4)
        else:
            avg_er = 0.0

        # Build platform breakdown
        distinct_platforms = sorted(list(set(acc.platform for acc in accounts)))
        platforms_breakdown: List[PlatformBreakdownItem] = []
        for plat in distinct_platforms:
            p_views = platform_views[plat] or platform_post_views[plat]
            p_inter = platform_interactions[plat]
            p_er_c = platform_er_count[plat]
            p_er = round(platform_er_sum[plat] / p_er_c, 4) if p_er_c > 0 else 0.0

            platforms_breakdown.append(
                PlatformBreakdownItem(
                    platform=plat,
                    accounts_count=platform_acc_count[plat],
                    followers_count=platform_followers[plat],
                    views_count=p_views,
                    posts_count=platform_posts_count[plat],
                    interactions_count=p_inter,
                    engagement_rate=p_er,
                )
            )

        # Growth overview
        growth = await self.get_growth_overview(db, user_id=user_id, platform=platform)

        # Overall total views: prefer channel-level total views if present, else sum of post views
        total_views = total_views_from_channels if total_views_from_channels > 0 else total_post_views

        return InsightsSummaryResponse(
            total_channels=len(accounts),
            total_posts=total_posts,
            total_followers=total_followers,
            total_views=total_views,
            total_interactions=total_interactions,
            average_engagement_rate=avg_er,
            platforms=platforms_breakdown,
            growth=growth,
            cached=False,
            generated_at=datetime.now(timezone.utc),
        )

    # -------------------------------------------------------------
    # Top Performing Content
    # -------------------------------------------------------------

    async def get_top_performing_content(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        platform: Optional[str] = None,
        account_id: Optional[uuid.UUID] = None,
        post_type: Optional[str] = None,
        limit: int = 10,
        sort_by: str = "engagement_rate",
        days: int = 30,
    ) -> TopContentResponse:
        """
        Fetch top performing posts ranked by engagement rate or selected metric over timeframe.
        """
        since = datetime.now(timezone.utc) - timedelta(days=days)

        # 1. Base query for posts
        post_q = (
            select(Post, PlatformAccount)
            .join(PlatformAccount, Post.platform_account_id == PlatformAccount.id)
            .where(
                PlatformAccount.user_id == user_id,
                PlatformAccount.is_active == True,
                Post.published_at >= since,
            )
        )

        if platform:
            post_q = post_q.where(PlatformAccount.platform == platform.lower())
        if account_id:
            post_q = post_q.where(Post.platform_account_id == account_id)
        if post_type:
            post_q = post_q.where(Post.post_type == post_type.lower())

        post_res = await db.execute(post_q)
        post_tuples = post_res.all()

        if not post_tuples:
            return TopContentResponse(
                total=0,
                sort_by=sort_by,
                timeframe_days=days,
                items=[],
            )

        post_ids = [p.id for p, _ in post_tuples]
        post_map = {p.id: (p, acc) for p, acc in post_tuples}

        # 2. Get latest snapshot for each matched post
        subq = (
            select(
                MetricSnapshot,
                func.row_number().over(
                    partition_by=MetricSnapshot.post_id,
                    order_by=MetricSnapshot.captured_at.desc(),
                ).label("rn"),
            )
            .where(
                MetricSnapshot.entity_type == "post",
                MetricSnapshot.post_id.in_(post_ids),
            )
            .subquery()
        )

        snap_q = select(MetricSnapshot).join(subq, MetricSnapshot.id == subq.c.id).where(subq.c.rn == 1)
        snap_res = await db.execute(snap_q)
        latest_snaps = {s.post_id: s for s in snap_res.scalars().all()}

        items: List[TopPostItem] = []
        for post_id, (post, acc) in post_map.items():
            snap = latest_snaps.get(post_id)
            views = snap.views_count if snap else 0
            likes = snap.likes_count if snap else 0
            comments = snap.comments_count if snap else 0
            shares = snap.shares_count if snap else 0
            saves = snap.saves_count if snap else 0
            er = snap.engagement_rate if snap else 0.0

            if snap and (er == 0.0 or er is None):
                er = calculate_engagement_rate(likes, comments, shares, saves, views)

            items.append(
                TopPostItem(
                    id=post.id,
                    platform=acc.platform,
                    platform_post_id=post.platform_post_id,
                    platform_account_id=acc.id,
                    channel_name=acc.account_name,
                    title=post.title,
                    content=post.content,
                    url=post.url,
                    thumbnail_url=post.thumbnail_url,
                    post_type=post.post_type,
                    published_at=post.published_at,
                    views_count=views,
                    likes_count=likes,
                    comments_count=comments,
                    shares_count=shares,
                    saves_count=saves,
                    engagement_rate=er,
                )
            )

        # 3. Sort items according to sort_by
        sort_key_map = {
            "engagement_rate": lambda x: x.engagement_rate,
            "views_count": lambda x: x.views_count,
            "likes_count": lambda x: x.likes_count,
            "comments_count": lambda x: x.comments_count,
            "shares_count": lambda x: x.shares_count,
        }
        key_fn = sort_key_map.get(sort_by.lower(), lambda x: x.engagement_rate)
        items.sort(key=key_fn, reverse=True)

        return TopContentResponse(
            total=len(items),
            sort_by=sort_by,
            timeframe_days=days,
            items=items[:limit],
        )

    # -------------------------------------------------------------
    # Time-Series Analytics for Charts
    # -------------------------------------------------------------

    async def get_timeseries_overview(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        platform: Optional[str] = None,
        account_id: Optional[uuid.UUID] = None,
        days: int = 30,
    ) -> TimeSeriesResponse:
        """
        Aggregate daily snapshot metric points over the specified timeframe for trend charts.
        """
        since = datetime.now(timezone.utc) - timedelta(days=days)

        # Fetch relevant platform accounts
        acc_q = select(PlatformAccount).where(
            PlatformAccount.user_id == user_id,
            PlatformAccount.is_active == True,
        )
        if platform:
            acc_q = acc_q.where(PlatformAccount.platform == platform.lower())
        if account_id:
            acc_q = acc_q.where(PlatformAccount.id == account_id)

        acc_res = await db.execute(acc_q)
        accounts = list(acc_res.scalars().all())

        if not accounts:
            return TimeSeriesResponse(
                timeframe_days=days,
                platform=platform,
                account_id=account_id,
                points=[],
            )

        account_ids = [acc.id for acc in accounts]

        # Fetch channel snapshots in timeframe
        snap_q = (
            select(MetricSnapshot)
            .where(
                MetricSnapshot.platform_account_id.in_(account_ids),
                MetricSnapshot.captured_at >= since,
            )
            .order_by(MetricSnapshot.captured_at.asc())
        )
        snap_res = await db.execute(snap_q)
        snapshots = list(snap_res.scalars().all())

        # Group by YYYY-MM-DD
        daily_data = defaultdict(lambda: {
            "views_count": 0,
            "followers_count": 0,
            "likes_count": 0,
            "comments_count": 0,
            "shares_count": 0,
            "saves_count": 0,
            "er_sum": 0.0,
            "er_count": 0,
        })

        for s in snapshots:
            d_str = s.captured_at.strftime("%Y-%m-%d")
            d_dict = daily_data[d_str]

            if s.entity_type == "channel":
                d_dict["followers_count"] = max(d_dict["followers_count"], s.followers_count)
                d_dict["views_count"] = max(d_dict["views_count"], s.views_count)
            else:
                d_dict["views_count"] += s.views_count
                d_dict["likes_count"] += s.likes_count
                d_dict["comments_count"] += s.comments_count
                d_dict["shares_count"] += s.shares_count
                d_dict["saves_count"] += s.saves_count
                d_dict["er_sum"] += s.engagement_rate
                d_dict["er_count"] += 1

        points: List[TimeSeriesPoint] = []
        for d_str in sorted(daily_data.keys()):
            info = daily_data[d_str]
            er_c = info["er_count"]
            avg_er = round(info["er_sum"] / er_c, 4) if er_c > 0 else 0.0

            points.append(
                TimeSeriesPoint(
                    date=d_str,
                    views_count=info["views_count"],
                    followers_count=info["followers_count"],
                    likes_count=info["likes_count"],
                    comments_count=info["comments_count"],
                    shares_count=info["shares_count"],
                    saves_count=info["saves_count"],
                    engagement_rate=avg_er,
                )
            )

        return TimeSeriesResponse(
            timeframe_days=days,
            platform=platform,
            account_id=account_id,
            points=points,
        )

    # -------------------------------------------------------------
    # Channel & Post Listing Helpers
    # -------------------------------------------------------------

    async def get_channels_with_metrics(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        platform: Optional[str] = None,
    ) -> List[ChannelDetailResponse]:
        """Fetch all connected channels for a user along with their latest snapshot metrics and post count."""
        q = select(PlatformAccount).where(PlatformAccount.user_id == user_id)
        if platform:
            q = q.where(PlatformAccount.platform == platform.lower())
        q = q.order_by(PlatformAccount.created_at.desc())
        res = await db.execute(q)
        accounts = list(res.scalars().all())

        channels: List[ChannelDetailResponse] = []
        for acc in accounts:
            latest_snap = await self.get_latest_channel_snapshot(db, acc.id)
            post_count_q = select(func.count(Post.id)).where(Post.platform_account_id == acc.id)
            post_count_res = await db.execute(post_count_q)
            p_count = post_count_res.scalar() or 0

            snap_resp = MetricSnapshotResponse.model_validate(latest_snap) if latest_snap else None

            channels.append(
                ChannelDetailResponse(
                    id=acc.id,
                    platform=acc.platform,
                    platform_account_id=acc.platform_account_id,
                    account_name=acc.account_name,
                    account_handle=acc.account_handle,
                    avatar_url=acc.avatar_url,
                    is_active=acc.is_active,
                    metadata_json=acc.metadata_json,
                    created_at=acc.created_at,
                    updated_at=acc.updated_at,
                    latest_snapshot=snap_resp,
                    posts_count=p_count,
                )
            )

        return channels

    async def get_user_posts(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        platform: Optional[str] = None,
        account_id: Optional[uuid.UUID] = None,
        post_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> PostListResponse:
        """List user's posts with pagination, filters, and latest metrics."""
        # Query accounts
        acc_q = select(PlatformAccount).where(PlatformAccount.user_id == user_id)
        if platform:
            acc_q = acc_q.where(PlatformAccount.platform == platform.lower())
        if account_id:
            acc_q = acc_q.where(PlatformAccount.id == account_id)
        acc_res = await db.execute(acc_q)
        accounts = list(acc_res.scalars().all())

        if not accounts:
            return PostListResponse(total=0, page=page, page_size=page_size, items=[])

        acc_map = {acc.id: acc for acc in accounts}
        account_ids = list(acc_map.keys())

        # Base post query
        base_q = select(Post).where(Post.platform_account_id.in_(account_ids))
        if post_type:
            base_q = base_q.where(Post.post_type == post_type.lower())

        # Total count
        count_q = select(func.count(Post.id)).where(Post.platform_account_id.in_(account_ids))
        if post_type:
            count_q = count_q.where(Post.post_type == post_type.lower())
        count_res = await db.execute(count_q)
        total = count_res.scalar() or 0

        # Paginate
        offset = (page - 1) * page_size
        paged_q = base_q.order_by(Post.published_at.desc()).offset(offset).limit(page_size)
        paged_res = await db.execute(paged_q)
        posts = list(paged_res.scalars().all())

        if not posts:
            return PostListResponse(total=total, page=page, page_size=page_size, items=[])

        post_ids = [p.id for p in posts]

        # Fetch latest snapshots for these posts
        subq = (
            select(
                MetricSnapshot,
                func.row_number().over(
                    partition_by=MetricSnapshot.post_id,
                    order_by=MetricSnapshot.captured_at.desc(),
                ).label("rn"),
            )
            .where(
                MetricSnapshot.entity_type == "post",
                MetricSnapshot.post_id.in_(post_ids),
            )
            .subquery()
        )

        snap_q = select(MetricSnapshot).join(subq, MetricSnapshot.id == subq.c.id).where(subq.c.rn == 1)
        snap_res = await db.execute(snap_q)
        latest_snaps = {s.post_id: s for s in snap_res.scalars().all()}

        items: List[PostWithMetricsResponse] = []
        for p in posts:
            acc = acc_map.get(p.platform_account_id)
            snap = latest_snaps.get(p.id)
            snap_resp = MetricSnapshotResponse.model_validate(snap) if snap else None

            items.append(
                PostWithMetricsResponse(
                    id=p.id,
                    platform_account_id=p.platform_account_id,
                    platform_post_id=p.platform_post_id,
                    post_type=p.post_type,
                    title=p.title,
                    content=p.content,
                    url=p.url,
                    thumbnail_url=p.thumbnail_url,
                    published_at=p.published_at,
                    metadata_json=p.metadata_json,
                    created_at=p.created_at,
                    updated_at=p.updated_at,
                    channel_name=acc.account_name if acc else None,
                    platform=acc.platform if acc else None,
                    latest_metrics=snap_resp,
                )
            )

        return PostListResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=items,
        )


analytics_service = AnalyticsService()

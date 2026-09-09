import uuid
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING
from sqlalchemy import BigInteger, Float, ForeignKey, String, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.platform_account import PlatformAccount
    from app.models.post import Post


class MetricSnapshot(Base, UUIDMixin, TimestampMixin):
    """Time-series snapshot for channel-level and post-level metrics."""
    __tablename__ = "metric_snapshots"

    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # 'channel' or 'post'
    
    # FK for Channel metrics
    platform_account_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("platform_accounts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    
    # FK for Post metrics
    post_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Core Social Metrics
    views_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    likes_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    comments_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    shares_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    saves_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    
    # Channel level specific metrics
    followers_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)  # Subs or Followers
    total_videos_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    # Calculated rates
    engagement_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    watch_time_minutes: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Snapshot Timestamp
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    # Relationships
    platform_account: Mapped[Optional["PlatformAccount"]] = relationship("PlatformAccount", back_populates="snapshots")
    post: Mapped[Optional["Post"]] = relationship("Post", back_populates="snapshots")

    def __repr__(self) -> str:
        return f"<MetricSnapshot {self.entity_type} at {self.captured_at}>"

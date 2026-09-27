import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from sqlalchemy import ForeignKey, String, Text, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.platform_account import PlatformAccount
    from app.models.metric_snapshot import MetricSnapshot


class Post(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "posts"

    platform_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("platform_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform_post_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    post_type: Mapped[str] = mapped_column(String(50), default="video", nullable=False)  # video, short, reel, photo, text, thread
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=True)

    # Relationships
    platform_account: Mapped["PlatformAccount"] = relationship("PlatformAccount", back_populates="posts")
    snapshots: Mapped[List["MetricSnapshot"]] = relationship("MetricSnapshot", back_populates="post", cascade="all, delete-orphan", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Post {self.platform_post_id}: {self.title or self.content[:30]}>"

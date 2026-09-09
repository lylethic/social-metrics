import uuid
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from sqlalchemy import Boolean, ForeignKey, String, Text, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.post import Post
    from app.models.metric_snapshot import MetricSnapshot


class PlatformAccount(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "platform_accounts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # youtube, facebook, instagram, threads, tiktok
    platform_account_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    account_name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_handle: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    # OAuth Tokens (will be encrypted in production)
    access_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Extra platform specific metadata
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="platform_accounts")
    posts: Mapped[List["Post"]] = relationship("Post", back_populates="platform_account", cascade="all, delete-orphan", lazy="selectin")
    snapshots: Mapped[List["MetricSnapshot"]] = relationship("MetricSnapshot", back_populates="platform_account", cascade="all, delete-orphan", lazy="selectin")

    def __repr__(self) -> str:
        return f"<PlatformAccount {self.platform}:{self.account_name}>"

"""create platform_accounts, posts and metric_snapshots tables

Revision ID: 0002_create_platform_tables
Revises: 0001_create_users_table
Create Date: 2026-09-05 11:05:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0002_create_platform_tables'
down_revision: Union[str, None] = '0001_create_users_table'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. platform_accounts table
    op.create_table(
        'platform_accounts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('platform', sa.String(length=50), nullable=False),
        sa.Column('platform_account_id', sa.String(length=255), nullable=False),
        sa.Column('account_name', sa.String(length=255), nullable=False),
        sa.Column('account_handle', sa.String(length=255), nullable=True),
        sa.Column('avatar_url', sa.String(length=500), nullable=True),
        sa.Column('access_token', sa.Text(), nullable=True),
        sa.Column('refresh_token', sa.Text(), nullable=True),
        sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(op.f('ix_platform_accounts_id'), 'platform_accounts', ['id'], unique=False)
    op.create_index(op.f('ix_platform_accounts_user_id'), 'platform_accounts', ['user_id'], unique=False)
    op.create_index(op.f('ix_platform_accounts_platform'), 'platform_accounts', ['platform'], unique=False)
    op.create_index(op.f('ix_platform_accounts_platform_account_id'), 'platform_accounts', ['platform_account_id'], unique=False)

    # 2. posts table
    op.create_table(
        'posts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('platform_account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('platform_accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('platform_post_id', sa.String(length=255), nullable=False),
        sa.Column('post_type', sa.String(length=50), nullable=False, server_default='video'),
        sa.Column('title', sa.String(length=500), nullable=True),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('url', sa.String(length=500), nullable=True),
        sa.Column('thumbnail_url', sa.String(length=500), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(op.f('ix_posts_id'), 'posts', ['id'], unique=False)
    op.create_index(op.f('ix_posts_platform_account_id'), 'posts', ['platform_account_id'], unique=False)
    op.create_index(op.f('ix_posts_platform_post_id'), 'posts', ['platform_post_id'], unique=False)
    op.create_index(op.f('ix_posts_published_at'), 'posts', ['published_at'], unique=False)

    # 3. metric_snapshots table
    op.create_table(
        'metric_snapshots',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('entity_type', sa.String(length=50), nullable=False),
        sa.Column('platform_account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('platform_accounts.id', ondelete='CASCADE'), nullable=True),
        sa.Column('post_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('posts.id', ondelete='CASCADE'), nullable=True),
        sa.Column('views_count', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('likes_count', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('comments_count', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('shares_count', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('saves_count', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('followers_count', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('total_videos_count', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('engagement_rate', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('watch_time_minutes', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(op.f('ix_metric_snapshots_id'), 'metric_snapshots', ['id'], unique=False)
    op.create_index(op.f('ix_metric_snapshots_entity_type'), 'metric_snapshots', ['entity_type'], unique=False)
    op.create_index(op.f('ix_metric_snapshots_platform_account_id'), 'metric_snapshots', ['platform_account_id'], unique=False)
    op.create_index(op.f('ix_metric_snapshots_post_id'), 'metric_snapshots', ['post_id'], unique=False)
    op.create_index(op.f('ix_metric_snapshots_captured_at'), 'metric_snapshots', ['captured_at'], unique=False)


def downgrade() -> None:
    op.drop_table('metric_snapshots')
    op.drop_table('posts')
    op.drop_table('platform_accounts')

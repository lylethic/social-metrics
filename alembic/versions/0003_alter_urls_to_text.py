"""alter avatar_url, url, thumbnail_url to text

Revision ID: 0003_alter_urls_to_text
Revises: 0002_create_platform_tables
Create Date: 2026-09-19 10:40:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic (max 32 chars).
revision: str = '0003_alter_urls_to_text'
down_revision: Union[str, None] = '0002_create_platform_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'platform_accounts',
        'avatar_url',
        existing_type=sa.String(length=500),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        'posts',
        'url',
        existing_type=sa.String(length=500),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        'posts',
        'thumbnail_url',
        existing_type=sa.String(length=500),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        'posts',
        'thumbnail_url',
        existing_type=sa.Text(),
        type_=sa.String(length=500),
        existing_nullable=True,
    )
    op.alter_column(
        'posts',
        'url',
        existing_type=sa.Text(),
        type_=sa.String(length=500),
        existing_nullable=True,
    )
    op.alter_column(
        'platform_accounts',
        'avatar_url',
        existing_type=sa.Text(),
        type_=sa.String(length=500),
        existing_nullable=True,
    )

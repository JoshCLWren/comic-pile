"""Add image optimization cache table.

Revision ID: 20261012034501
Revises: m5d300000001
Create Date: 2026-10-12 03:45:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import BYTEA

revision = "20261012034501"
down_revision = "m5d300000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create image_optimization_cache table."""
    op.create_table(
        "image_optimization_cache",
        sa.Column("cache_key", sa.String(length=512), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("content", BYTEA(), nullable=False),
        sa.Column("media_type", sa.String(length=100), nullable=False),
        sa.Column("transcoded", sa.Boolean(), nullable=False),
        sa.Column("content_length", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("cache_key"),
    )
    op.create_index(
        "ix_image_optimization_cache_expires_at",
        "image_optimization_cache",
        ["expires_at"],
    )
    op.create_index(
        "ix_image_optimization_cache_source_url_width",
        "image_optimization_cache",
        ["source_url", "width"],
    )


def downgrade() -> None:
    """Drop image_optimization_cache table."""
    op.drop_index("ix_image_optimization_cache_source_url_width", table_name="image_optimization_cache")
    op.drop_index("ix_image_optimization_cache_expires_at", table_name="image_optimization_cache")
    op.drop_table("image_optimization_cache")

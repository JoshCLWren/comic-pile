"""Add reading plan release sources (#3116).

Revision ID: e913be4e091d
Revises: n6e300000001
Create Date: 2026-10-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e913be4e091d"
down_revision: Union[str, Sequence[str], None] = "n6e300000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the reading_plan_release_sources table."""
    op.create_table(
        "reading_plan_release_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("thread_id", sa.Integer(), nullable=False),
        sa.Column("external_identity_id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["continuity_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["external_identity_id"], ["external_identities.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "plan_id",
            "thread_id",
            "external_identity_id",
            name="uq_release_source_once_per_plan_thread_volume",
        ),
    )
    op.create_index(
        "ix_release_sources_plan_id", "reading_plan_release_sources", ["plan_id"]
    )
    op.create_index(
        "ix_release_sources_thread_id", "reading_plan_release_sources", ["thread_id"]
    )
    op.create_index(
        "ix_release_sources_enabled", "reading_plan_release_sources", ["enabled"]
    )


def downgrade() -> None:
    """Drop the reading_plan_release_sources table."""
    op.drop_index("ix_release_sources_enabled", "reading_plan_release_sources")
    op.drop_index("ix_release_sources_thread_id", "reading_plan_release_sources")
    op.drop_index("ix_release_sources_plan_id", "reading_plan_release_sources")
    op.drop_table("reading_plan_release_sources")

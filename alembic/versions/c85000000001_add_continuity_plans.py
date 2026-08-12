"""Add persisted continuity plans.

Revision ID: c85000000001
Revises: c84900000001
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "c85000000001"
down_revision: str | None = "c84900000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create user-scoped continuity plan storage."""
    op.create_table(
        "continuity_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("ordering_mode", sa.String(length=32), nullable=False),
        sa.Column("nodes_json", sa.JSON(), nullable=False),
        sa.Column("lanes_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "ordering_mode IN ('informational', 'strict_sequential')",
            name="ck_continuity_plans_ordering_mode",
        ),
    )
    op.create_index("ix_continuity_plans_user_id", "continuity_plans", ["user_id"])


def downgrade() -> None:
    """Remove continuity plan storage."""
    op.drop_index("ix_continuity_plans_user_id", table_name="continuity_plans")
    op.drop_table("continuity_plans")

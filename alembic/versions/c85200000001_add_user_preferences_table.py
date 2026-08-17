"""Add user_preferences table for per-user theme persistence.

Revision ID: c85200000001
Revises: c85100000001
Create Date: 2026-08-17 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c85200000001"
down_revision: str | Sequence[str] | None = "c85100000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the user_preferences table."""
    op.create_table(
        "user_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_user_preferences_user_id_users", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "theme",
            sa.String(50),
            nullable=False,
            server_default="classic",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_user_preferences_user_id"),
    )
    op.create_index("ix_user_preferences_user_id", "user_preferences", ["user_id"])


def downgrade() -> None:
    """Drop the user_preferences table."""
    op.drop_index("ix_user_preferences_user_id", table_name="user_preferences")
    op.drop_table("user_preferences")

"""Add failed_login_attempts table for account lockout.

Revision ID: a7b8c9d0e1f2
Revises: b9ec6f922a61
Create Date: 2026-04-19 16:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "a7b8c9d0e1f2"
down_revision: str | Sequence[str] | None = "b9ec6f922a61"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "failed_login_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(50), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=False),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_failed_login_username_time",
        "failed_login_attempts",
        ["username", "attempted_at"],
    )
    op.create_index(
        "ix_failed_login_ip_time",
        "failed_login_attempts",
        ["ip_address", "attempted_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_failed_login_ip_time", table_name="failed_login_attempts")
    op.drop_index("ix_failed_login_username_time", table_name="failed_login_attempts")
    op.drop_table("failed_login_attempts")

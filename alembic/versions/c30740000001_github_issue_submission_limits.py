"""Add durable per-user GitHub issue submission rate-limit state.

Revision ID: c30740000001
Revises: d41480000001
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c30740000001"
down_revision: str | Sequence[str] | None = "d41480000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the cross-instance rolling-hour limit table."""
    op.create_table(
        "github_issue_submission_limits",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("last_submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_github_issue_submission_limits_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    """Drop the rolling-hour limit table."""
    op.drop_table("github_issue_submission_limits")

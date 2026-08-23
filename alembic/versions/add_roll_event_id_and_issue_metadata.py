"""Add roll_event_id to events and issue metadata on roll events.

Revision ID: 0a1b2c3d4e5f
Revises: f8a3b2c1d4e5
Create Date: 2026-08-23 09:55:11.733867
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0a1b2c3d4e5f"
down_revision: str | Sequence[str] | None = "f8a3b2c1d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "roll_event_id",
                sa.Integer(),
                sa.ForeignKey("events.id", ondelete="SET NULL"),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "issue_id",
                sa.Integer(),
                sa.ForeignKey("issues.id", ondelete="SET NULL"),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "issue_number",
                sa.String(50),
                nullable=True,
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.drop_column("issue_number")
        batch_op.drop_column("issue_id")
        batch_op.drop_column("roll_event_id")
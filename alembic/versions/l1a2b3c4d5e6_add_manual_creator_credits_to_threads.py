"""Add manual creator credits to threads table.

Revision ID: l1a2b3c4d5e6
Revises: k4c100000001
Create Date: 2026-10-06 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "l1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = "k4c100000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "threads",
        sa.Column(
            "manual_creator_credits",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("threads", "manual_creator_credits")

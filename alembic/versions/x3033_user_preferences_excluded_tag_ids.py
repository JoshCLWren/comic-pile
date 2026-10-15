"""Add excluded tag IDs to user preferences for Roll tag exclusions.

Revision ID: x3033_user_preference_tag_exclusions
Revises: c36620000001
Create Date: 2026-08-04 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "x3033_user_preference_tag_exclusions"
down_revision: str | Sequence[str] | None = "c36620000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "user_preferences",
        sa.Column(
            "excluded_tag_ids",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("user_preferences", "excluded_tag_ids")

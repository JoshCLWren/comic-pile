"""Add persistent account-wide roll tag exclusions (issue #3033).

Revision ID: r303300000001
Revises: c36420000001
Create Date: 2026-10-13 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "r303300000001"
down_revision: str | Sequence[str] | None = "c36420000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the roll_tag_exclusions table.

    Args:
        None.

    Returns:
        None.
    """
    op.create_table(
        "roll_tag_exclusions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["tags.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_roll_tag_exclusions_user_id",
        "roll_tag_exclusions",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_roll_tag_exclusions_tag_id",
        "roll_tag_exclusions",
        ["tag_id"],
        unique=False,
    )
    op.create_index(
        "uq_roll_tag_exclusions_user_tag",
        "roll_tag_exclusions",
        ["user_id", "tag_id"],
        unique=True,
    )


def downgrade() -> None:
    """Drop the roll_tag_exclusions table.

    Args:
        None.

    Returns:
        None.
    """
    op.drop_index("uq_roll_tag_exclusions_user_tag", table_name="roll_tag_exclusions")
    op.drop_index("ix_roll_tag_exclusions_tag_id", table_name="roll_tag_exclusions")
    op.drop_index("ix_roll_tag_exclusions_user_id", table_name="roll_tag_exclusions")
    op.drop_table("roll_tag_exclusions")

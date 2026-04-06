"""Drop redundant ix_review_user_thread index

Revision ID: d744a8c62071
Revises: 84d72448ea93
Create Date: 2026-04-05 22:39:06.699245

"""

from collections.abc import Sequence

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d744a8c62071"
down_revision: str | Sequence[str] | None = "84d72448ea93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index("ix_review_user_thread", table_name="reviews")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_index("ix_review_user_thread", "reviews", ["user_id", "thread_id"])

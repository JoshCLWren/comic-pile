"""Add cascade delete on reviews.thread_id

Revision ID: 28148d574e9e
Revises: d744a8c62071
Create Date: 2026-04-05 22:42:04.052493

"""

from collections.abc import Sequence

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "28148d574e9e"
down_revision: str | Sequence[str] | None = "d744a8c62071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Drop existing foreign key constraint on thread_id
    op.drop_constraint("reviews_thread_id_fkey", "reviews", type_="foreignkey")
    # Recreate foreign key constraint with CASCADE delete
    op.create_foreign_key(
        "reviews_thread_id_fkey", "reviews", "threads", ["thread_id"], ["id"], ondelete="CASCADE"
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Revert to NO ACTION (the default)
    op.drop_constraint("reviews_thread_id_fkey", "reviews", type_="foreignkey")
    op.create_foreign_key("reviews_thread_id_fkey", "reviews", "threads", ["thread_id"], ["id"])

"""Add latest session action lookup index.

Revision ID: b700c1d2e3f4
Revises: a613b7c9d201
Create Date: 2026-08-04 18:05:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "b700c1d2e3f4"
down_revision: str | Sequence[str] | None = "a613b7c9d201"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Index deterministic latest-action reads by session without blocking writes.

    Args:
        None.

    Returns:
        None.
    """
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_event_session_latest_action",
            "events",
            ["session_id", sa.text("timestamp DESC"), sa.text("id DESC")],
            unique=False,
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    """Remove the latest-action lookup index without blocking writes.

    Args:
        None.

    Returns:
        None.
    """
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_event_session_latest_action",
            table_name="events",
            postgresql_concurrently=True,
        )

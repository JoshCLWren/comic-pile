"""Add latest session action lookup index.

Revision ID: b700c1d2e3f4
Revises: a613b7c9d201
Create Date: 2026-08-04 18:05:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "b700c1d2e3f4"
down_revision: str | Sequence[str] | None = "a613b7c9d201"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Index deterministic latest-action reads by session."""
    op.create_index(
        "ix_event_session_latest_action",
        "events",
        ["session_id", op.f("timestamp"), op.f("id")],
        unique=False,
        postgresql_ops={"timestamp": "DESC", "id": "DESC"},
    )


def downgrade() -> None:
    """Remove the latest-action lookup index."""
    op.drop_index("ix_event_session_latest_action", table_name="events")

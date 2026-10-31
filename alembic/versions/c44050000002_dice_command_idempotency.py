"""Enforce durable per-reader idempotency for Rust Roll dice commands.

Revision ID: c44050000002
Revises: c44050000001

Historical events and old session-based writers remain untouched. JSON event
context stores the immutable command payload/key, and the partial unique index
protects it across connections and process restarts.
"""

from alembic import op

revision = "c44050000002"
down_revision = "c44050000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX ix_events_user_dice_command_key
        ON events (user_id, ((context->>'dice_command_key')))
        WHERE (context->>'dice_command_key') IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_events_user_dice_command_key", table_name="events")

"""normalize naive datetimes to utc

Revision ID: f616f65e0f1f
Revises: 6017d4c472e3
Create Date: 2026-03-07 17:07:41.349955

"""

from collections.abc import Sequence

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f616f65e0f1f"
down_revision: str | Sequence[str] | None = "6017d4c472e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    Normalize any naive datetime values to UTC by treating them as local time
    and converting to UTC. This ensures consistent timezone-aware timestamps
    across all datetime columns.

    This migration addresses issue #245 where naive datetime values were being
    serialized differently than timezone-aware values, causing timestamp
    inconsistencies on the Session Details page.
    """
    # Normalize sessions.started_at - treat naive as local, convert to UTC
    op.execute("""
        UPDATE sessions
        SET started_at = started_at AT TIME ZONE 'UTC'
        WHERE started_at::text NOT LIKE '%+00%' AND started_at::text NOT LIKE '%Z'
    """)

    # Normalize sessions.ended_at - treat naive as local, convert to UTC
    op.execute("""
        UPDATE sessions
        SET ended_at = ended_at AT TIME ZONE 'UTC'
        WHERE ended_at IS NOT NULL
          AND ended_at::text NOT LIKE '%+00%'
          AND ended_at::text NOT LIKE '%Z'
    """)

    # Normalize sessions.pending_thread_updated_at - treat naive as local, convert to UTC
    op.execute("""
        UPDATE sessions
        SET pending_thread_updated_at = pending_thread_updated_at AT TIME ZONE 'UTC'
        WHERE pending_thread_updated_at IS NOT NULL
          AND pending_thread_updated_at::text NOT LIKE '%+00%'
          AND pending_thread_updated_at::text NOT LIKE '%Z'
    """)

    # Normalize snapshots.created_at - treat naive as local, convert to UTC
    op.execute("""
        UPDATE snapshots
        SET created_at = created_at AT TIME ZONE 'UTC'
        WHERE created_at::text NOT LIKE '%+00%' AND created_at::text NOT LIKE '%Z'
    """)

    # Normalize events.timestamp - treat naive as local, convert to UTC
    op.execute("""
        UPDATE events
        SET timestamp = timestamp AT TIME ZONE 'UTC'
        WHERE timestamp::text NOT LIKE '%+00%' AND timestamp::text NOT LIKE '%Z'
    """)


def downgrade() -> None:
    """Downgrade schema.

    Convert UTC timezone-aware datetimes back to naive by removing timezone info.
    This reverses the normalization and should only be used if rolling back
    to a version before this migration.
    """
    # Revert sessions.started_at - remove timezone info
    op.execute("""
        UPDATE sessions
        SET started_at = started_at AT TIME ZONE 'UTC' AT TIME ZONE 'UTC'
    """)

    # Revert sessions.ended_at - remove timezone info
    op.execute("""
        UPDATE sessions
        SET ended_at = ended_at AT TIME ZONE 'UTC' AT TIME ZONE 'UTC'
        WHERE ended_at IS NOT NULL
    """)

    # Revert sessions.pending_thread_updated_at - remove timezone info
    op.execute("""
        UPDATE sessions
        SET pending_thread_updated_at = pending_thread_updated_at AT TIME ZONE 'UTC' AT TIME ZONE 'UTC'
        WHERE pending_thread_updated_at IS NOT NULL
    """)

    # Revert snapshots.created_at - remove timezone info
    op.execute("""
        UPDATE snapshots
        SET created_at = created_at AT TIME ZONE 'UTC' AT TIME ZONE 'UTC'
    """)

    # Revert events.timestamp - remove timezone info
    op.execute("""
        UPDATE events
        SET timestamp = timestamp AT TIME ZONE 'UTC' AT TIME ZONE 'UTC'
    """)

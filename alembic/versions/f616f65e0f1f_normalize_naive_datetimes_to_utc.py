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

    Only processes columns that are actually timestamp without time zone,
    leaving timestamptz columns unchanged to avoid shifting instants.
    """
    # Normalize sessions.started_at - only if it's timestamp without time zone
    op.execute("""
        UPDATE sessions
        SET started_at = started_at AT TIME ZONE 'UTC'
        WHERE pg_typeof(started_at) = 'timestamp without time zone'::regtype
          AND started_at::text NOT LIKE '%+00%'
          AND started_at::text NOT LIKE '%Z'
    """)

    # Normalize sessions.ended_at - only if it's timestamp without time zone
    op.execute("""
        UPDATE sessions
        SET ended_at = ended_at AT TIME ZONE 'UTC'
        WHERE ended_at IS NOT NULL
          AND pg_typeof(ended_at) = 'timestamp without time zone'::regtype
          AND ended_at::text NOT LIKE '%+00%'
          AND ended_at::text NOT LIKE '%Z'
    """)

    # Normalize sessions.pending_thread_updated_at - only if it's timestamp without time zone
    op.execute("""
        UPDATE sessions
        SET pending_thread_updated_at = pending_thread_updated_at AT TIME ZONE 'UTC'
        WHERE pending_thread_updated_at IS NOT NULL
          AND pg_typeof(pending_thread_updated_at) = 'timestamp without time zone'::regtype
          AND pending_thread_updated_at::text NOT LIKE '%+00%'
          AND pending_thread_updated_at::text NOT LIKE '%Z'
    """)

    # Normalize snapshots.created_at - only if it's timestamp without time zone
    op.execute("""
        UPDATE snapshots
        SET created_at = created_at AT TIME ZONE 'UTC'
        WHERE pg_typeof(created_at) = 'timestamp without time zone'::regtype
          AND created_at::text NOT LIKE '%+00%'
          AND created_at::text NOT LIKE '%Z'
    """)

    # Normalize events.timestamp - only if it's timestamp without time zone
    op.execute("""
        UPDATE events
        SET timestamp = timestamp AT TIME ZONE 'UTC'
        WHERE pg_typeof(timestamp) = 'timestamp without time zone'::regtype
          AND timestamp::text NOT LIKE '%+00%'
          AND timestamp::text NOT LIKE '%Z'
    """)


def downgrade() -> None:
    """Downgrade schema.

    This migration is irreversible. Once naive datetimes are converted to
    timezone-aware timestamptz, we cannot accurately restore the original
    naive state without data loss.

    The columns sessions.started_at, sessions.ended_at,
    sessions.pending_thread_updated_at, snapshots.created_at, and
    events.timestamp are all timestamptz and will remain so after downgrade.
    """
    raise RuntimeError(
        "Irreversible migration: cannot restore naive datetimes from timestamptz. "
        "The following columns were converted to timezone-aware timestamps: "
        "sessions.started_at, sessions.ended_at, sessions.pending_thread_updated_at, "
        "snapshots.created_at, events.timestamp"
    )

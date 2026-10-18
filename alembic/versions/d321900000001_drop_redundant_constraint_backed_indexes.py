"""Drop redundant indexes already covered by uniqueness constraints.

Revision ID: d321900000001
Revises: c36690000001

Issue #3219: each ordinary index below sits on exactly the same keys as a
unique constraint's remaining backing index, so every lookup, range scan and
ordering those indexes supported is already served by the unique index:

- ``ix_issue_thread_position``      -> ``uq_issue_thread_position``  (issues(thread_id, position))
- ``ix_user_preferences_user_id``  -> unique user_id constraint   (user_preferences)
- ``ix_recommendation_contexts_event_id``
                                   -> unique event_id constraint   (recommendation_contexts)

Uniqueness, the deferred ``uq_issue_thread_position`` check, all foreign keys
and ownership guards are untouched; only the duplicate write-maintenance
indexes are removed. Deferrability affects when the uniqueness check fires,
not the structure or planner usability of the backing unique B-tree index.

Lock/timeout behavior: ``DROP INDEX`` takes a SHARE lock (reads stay allowed,
writes block) for the duration of the drop. ``DROP INDEX CONCURRENTLY`` would
avoid that lock but cannot run inside Alembic's migration transaction, so this
migration keeps transactional ``DROP INDEX`` and sets an explicit
``lock_timeout`` so it fails fast with a clear error instead of queueing
indefinitely behind concurrent writers. The timeout is applied with ``SET
LOCAL`` so it is scoped to this migration's transaction: a plain ``SET`` is
session-scoped, and Alembic reuses one connection for every revision in an
``upgrade``, which would silently impose this migration's five-second lock
budget on unrelated later revisions.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d321900000001"
down_revision: str | Sequence[str] | None = "c36690000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (index_name, table_name, columns) for each redundant ordinary index.
# Column lists are preserved so downgrade restores the exact prior definitions.
REDUNDANT_INDEXES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("ix_issue_thread_position", "issues", ("thread_id", "position")),
    ("ix_user_preferences_user_id", "user_preferences", ("user_id",)),
    (
        "ix_recommendation_contexts_event_id",
        "recommendation_contexts",
        ("event_id",),
    ),
)

# Fail fast instead of queueing behind writers while waiting for the SHARE lock.
# Transaction-scoped (SET LOCAL) so the budget never leaks to other revisions
# applied later on the same Alembic connection.
LOCK_TIMEOUT = "5s"


def upgrade() -> None:
    """Drop the three redundant constraint-backed indexes."""
    op.execute(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'")
    for index_name, table_name, _columns in REDUNDANT_INDEXES:
        op.drop_index(index_name, table_name=table_name)


def downgrade() -> None:
    """Restore the three redundant indexes with their original definitions."""
    op.execute(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'")
    for index_name, table_name, columns in REDUNDANT_INDEXES:
        op.create_index(index_name, table_name, list(columns))

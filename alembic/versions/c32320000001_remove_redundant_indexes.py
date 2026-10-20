"""Remove redundant indexes covered by unique constraints.

Revision ID: c32320000001
Revises: p322700000001
Create Date: 2026-10-19 00:00:00.000000

Removes redundant indexes that are already covered by unique constraints:
- ix_issue_thread_position on issues(thread_id, position) covered by uq_issue_thread_position
- ix_user_preferences_user_id on user_preferences(user_id) covered by unique constraint on user_id
- ix_recommendation_contexts_event_id on recommendation_contexts(event_id) covered by unique constraint on event_id

These indexes add storage and write maintenance overhead without providing additional
query coverage since the unique constraints already enforce the same uniqueness guarantee.

The downgrade restores those indexes and stays restartable. A concurrent build that
hits the statement timeout leaves the revision unapplied, so Alembic retries the
downgrade from the first index. The restore therefore skips indexes that an earlier
attempt already created and rebuilds indexes that a failed concurrent build left
behind in an invalid state instead of failing with "relation already exists".
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c32320000001"
down_revision: str | Sequence[str] | None = "p322700000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Keep the migration from waiting indefinitely for a conflicting lock. The
# drops and recreations run concurrently, so they do not take ACCESS EXCLUSIVE
# locks on the parent tables while the indexes are rebuilt.
LOCK_TIMEOUT = "5s"
STATEMENT_TIMEOUT = "120s"

# Indexes restored by the downgrade: name, owning table, and covered columns.
RESTORED_INDEXES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("ix_issue_thread_position", "issues", ("thread_id", "position")),
    ("ix_user_preferences_user_id", "user_preferences", ("user_id",)),
    ("ix_recommendation_contexts_event_id", "recommendation_contexts", ("event_id",)),
)

# Catalog states of an index that the downgrade has to tell apart.
INDEX_MISSING = "missing"
INDEX_INVALID = "invalid"
INDEX_VALID = "valid"


def _configure_timeouts() -> None:
    """Apply explicit lock and statement timeouts for the online DDL."""
    op.execute(f"SET lock_timeout = '{LOCK_TIMEOUT}'")
    op.execute(f"SET statement_timeout = '{STATEMENT_TIMEOUT}'")


def _reset_timeouts() -> None:
    """Restore the session timeouts so later migrations are unaffected."""
    op.execute("RESET lock_timeout")
    op.execute("RESET statement_timeout")


def _index_state(index_name: str) -> str:
    """Return the catalog state of an index.

    Args:
        index_name: Name of the index to inspect.

    Returns:
        ``INDEX_MISSING`` when the index does not exist, ``INDEX_INVALID`` when
        a failed concurrent build left an unusable index behind, and
        ``INDEX_VALID`` when the index exists and is usable by the planner.
    """
    if op.get_context().as_sql:
        # Offline SQL generation cannot inspect the live catalog, so emit the
        # create statements and let the operator resolve any leftover index.
        return INDEX_MISSING
    row = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT i.indisvalid "
                "FROM pg_catalog.pg_class c "
                "JOIN pg_catalog.pg_index i ON i.indexrelid = c.oid "
                "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
                "WHERE c.relname = :index_name "
                "AND n.nspname = current_schema()"
            ),
            {"index_name": index_name},
        )
        .first()
    )
    if row is None:
        return INDEX_MISSING
    return INDEX_VALID if row[0] else INDEX_INVALID


def _restore_index(index_name: str, table_name: str, columns: tuple[str, ...]) -> None:
    """Recreate one removed index, recovering from a partially applied downgrade.

    Args:
        index_name: Name of the index to restore.
        table_name: Table that owns the index.
        columns: Columns covered by the index.
    """
    state = _index_state(index_name)
    if state == INDEX_VALID:
        # An earlier downgrade attempt already restored this index.
        return
    if state == INDEX_INVALID:
        # A failed concurrent build left an unusable index behind. Drop it so
        # the rebuild below produces an index the planner can use.
        op.drop_index(
            index_name,
            table_name=table_name,
            if_exists=True,
            postgresql_concurrently=True,
        )
    op.create_index(
        index_name,
        table_name,
        list(columns),
        unique=False,
        if_not_exists=True,
        postgresql_concurrently=True,
    )


def upgrade() -> None:
    """Remove redundant indexes covered by unique constraints.

    Drops the following redundant indexes:
    - ix_issue_thread_position on issues table (covered by uq_issue_thread_position constraint)
    - ix_user_preferences_user_id on user_preferences table (covered by unique user_id constraint)
    - ix_recommendation_contexts_event_id on recommendation_contexts table (covered by unique event_id constraint)
    """
    # DROP INDEX CONCURRENTLY cannot run inside a transaction block.
    with op.get_context().autocommit_block():
        _configure_timeouts()
        try:
            # Remove redundant index from issues table - covered by uq_issue_thread_position constraint
            op.drop_index(
                "ix_issue_thread_position",
                table_name="issues",
                if_exists=True,
                postgresql_concurrently=True,
            )
            # Remove redundant index from user_preferences table - covered by unique user_id constraint
            op.drop_index(
                "ix_user_preferences_user_id",
                table_name="user_preferences",
                if_exists=True,
                postgresql_concurrently=True,
            )
            # Remove redundant index from recommendation_contexts table - covered by unique event_id constraint
            op.drop_index(
                "ix_recommendation_contexts_event_id",
                table_name="recommendation_contexts",
                if_exists=True,
                postgresql_concurrently=True,
            )
        finally:
            _reset_timeouts()


def downgrade() -> None:
    """Restore the redundant indexes that were removed.

    Recreates the indexes that were removed in the upgrade operation. The
    restore is restartable: it skips indexes that an earlier attempt already
    created and rebuilds indexes that a failed concurrent build left invalid.
    """
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction block.
    with op.get_context().autocommit_block():
        _configure_timeouts()
        try:
            for index_name, table_name, columns in RESTORED_INDEXES:
                _restore_index(index_name, table_name, columns)
        finally:
            _reset_timeouts()

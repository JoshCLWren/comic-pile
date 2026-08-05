"""Drop the retired Reviews persistence.

Revision ID: 7f41d0a9c2e1
Revises: b700c1d2e3f4
Create Date: 2026-08-05 08:55:00.000000

The Reviews product surface was removed before this migration. Production data
must be verified as no longer needed before applying this irreversible cleanup.
"""

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7f41d0a9c2e1"
down_revision: str | Sequence[str] | None = "b700c1d2e3f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONFIRMATION_ENV = "CONFIRM_DROP_REVIEWS_ROW_COUNT"
AUDIT_TABLE = "migration_data_deletion_audit"


def _verified_row_count() -> int:
    """Return the confirmed number of retained review rows."""
    actual_count = int(op.get_bind().execute(sa.text("SELECT COUNT(*) FROM reviews")).scalar_one())
    if actual_count == 0:
        return actual_count

    expected_count = os.getenv(CONFIRMATION_ENV)
    if expected_count is None:
        raise RuntimeError(
            f"Set {CONFIRMATION_ENV} to the verified production reviews row count "
            f"before applying this irreversible migration (current count: {actual_count})."
        )
    try:
        confirmed_count = int(expected_count)
    except ValueError as exc:
        raise RuntimeError(f"{CONFIRMATION_ENV} must be an integer row count.") from exc
    if confirmed_count != actual_count:
        raise RuntimeError(
            f"Verified reviews row count changed: expected {confirmed_count}, found {actual_count}. "
            "Re-check retained data before applying this irreversible migration."
        )
    return actual_count


def _record_deletion_scope(row_count: int) -> None:
    """Persist the confirmed deletion scope before removing Reviews data."""
    op.create_table(
        AUDIT_TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("migration_revision", sa.String(length=32), nullable=False),
        sa.Column("resource", sa.String(length=100), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.get_bind().execute(
        sa.text(
            f"INSERT INTO {AUDIT_TABLE} (migration_revision, resource, row_count) "
            "VALUES (:migration_revision, :resource, :row_count)"
        ),
        {
            "migration_revision": revision,
            "resource": "reviews",
            "row_count": row_count,
        },
    )


def upgrade() -> None:
    """Remove orphaned Reviews storage and thread metadata.

    Args:
        None.

    Returns:
        None.
    """
    row_count = _verified_row_count()
    _record_deletion_scope(row_count)
    op.drop_table("reviews")

    with op.batch_alter_table("threads", schema=None) as batch_op:
        batch_op.drop_column("review_url")
        batch_op.drop_column("last_review_at")


def downgrade() -> None:
    """Refuse to recreate destructively removed review data.

    Args:
        None.

    Returns:
        None.
    """
    raise RuntimeError(
        "The retired Reviews data cannot be restored by downgrade; restore a database backup instead."
    )

"""Drop the retired Reviews persistence.

Revision ID: 7f41d0a9c2e1
Revises: b700c1d2e3f4
Create Date: 2026-08-05 08:55:00.000000

The Reviews product surface and its retained data are intentionally removed by
this migration. The deleted row count is recorded for auditability before the
irreversible table drop.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7f41d0a9c2e1"
down_revision: str | Sequence[str] | None = "b700c1d2e3f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AUDIT_TABLE = "migration_data_deletion_audit"


def _locked_row_count() -> int:
    """Lock Reviews writes and return the exact number of rows being removed."""
    bind = op.get_bind()
    bind.execute(sa.text("LOCK TABLE reviews IN ACCESS EXCLUSIVE MODE"))
    return int(bind.execute(sa.text("SELECT COUNT(*) FROM reviews")).scalar_one())


def _record_deletion_scope(row_count: int) -> None:
    """Persist the deletion scope before removing Reviews data."""
    op.create_table(
        AUDIT_TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("migration_revision", sa.String(length=32), nullable=False),
        sa.Column("resource", sa.String(length=100), nullable=False),
        sa.Column("row_count", sa.BigInteger(), nullable=False),
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
    """Remove retired Reviews storage and thread metadata."""
    row_count = _locked_row_count()
    _record_deletion_scope(row_count)
    op.drop_table("reviews")

    with op.batch_alter_table("threads", schema=None) as batch_op:
        batch_op.drop_column("review_url")
        batch_op.drop_column("last_review_at")


def downgrade() -> None:
    """Refuse to recreate destructively removed review data."""
    raise RuntimeError(
        "The retired Reviews data cannot be restored by downgrade; restore a database backup instead."
    )

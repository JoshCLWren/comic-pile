"""Add queryable snapshot kind/schema-version metadata for delta lookup.

Revision ID: f2a3b4c5d6e7
Revises: c86100000001
Create Date: 2026-10-10

Issue #3218: ``get_latest_delta_snapshot`` loads every snapshot payload and
scans ``_version`` in Python. These additive nullable columns let the newest
supported unconsumed delta be selected with SQL filtering, deterministic
``created_at``/``id`` ordering, ``LIMIT 1`` and a matching composite index.

The backfill derives classification from the real snapshot contract and never
drops rows: NULL, non-object, unversioned and unsupported-version payloads all
receive a kind. Integral float versions (``2.0``) normalize the same way as
``app.services.snapshot_contract.classify_snapshot``; digit strings longer
than nine characters cannot be real schema versions and stay unversioned so
the integer cast can never overflow.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f2a3b4c5d6e7"
down_revision = "c86100000001"
branch_labels: str | None = None
depends_on: str | None = None

# Version expression shared by the kind and schema_version assignments. Kept
# as a module constant so the migration regression test can execute the exact
# same SQL without an Alembic context.
#
# ``->>`` stringifies every JSON value, so the raw ``->`` operand is first
# gated on ``jsonb_typeof = 'number'``: a string "2" must stay unversioned
# exactly like ``classify_snapshot`` treats it, while numeric 2 and 2.0 map
# to schema version 2.
_RAW_VERSION_SQL = (
    "(CASE WHEN jsonb_typeof(snapshots.thread_states::jsonb -> '_version') = 'number' "
    "THEN snapshots.thread_states::jsonb ->> '_version' ELSE NULL END)"
)
_INTEGER_VERSION_SQL = (
    f"(CASE WHEN {_RAW_VERSION_SQL} ~ '^-?[0-9]{{1,9}}$' THEN {_RAW_VERSION_SQL}::integer "
    f"WHEN {_RAW_VERSION_SQL} ~ '^-?[0-9]{{1,9}}\\.0+$' "
    f"THEN split_part({_RAW_VERSION_SQL}, '.', 1)::integer ELSE NULL END)"
)

BACKFILL_SQL = f"""UPDATE snapshots SET
  schema_version = {_INTEGER_VERSION_SQL},
  snapshot_kind = CASE
    WHEN {_INTEGER_VERSION_SQL} IS NOT NULL THEN 'delta'
    WHEN jsonb_typeof(snapshots.thread_states::jsonb) IS DISTINCT FROM 'object'
      THEN 'unknown'
    WHEN snapshots.description = 'Session start' AND snapshots.event_id IS NULL
      THEN 'session_start'
    ELSE 'legacy_full'
  END
WHERE snapshots.snapshot_kind IS NULL"""


def upgrade() -> None:
    """Add nullable classification columns, backfill them, and index lookups."""
    op.add_column("snapshots", sa.Column("snapshot_kind", sa.String(20), nullable=True))
    op.add_column("snapshots", sa.Column("schema_version", sa.Integer(), nullable=True))
    op.execute(sa.text(BACKFILL_SQL))
    op.create_index(
        "ix_snapshot_session_delta_lookup",
        "snapshots",
        ["session_id", "snapshot_kind", "schema_version", "created_at", "id"],
    )


def downgrade() -> None:
    """Drop the lookup index and classification columns.

    Payloads are untouched, so downgrade only removes queryability: older code
    resumes the full-stack Python scan. Rows written while the columns existed
    keep their JSON payloads intact.
    """
    op.drop_index("ix_snapshot_session_delta_lookup", table_name="snapshots")
    op.drop_column("snapshots", "schema_version")
    op.drop_column("snapshots", "snapshot_kind")

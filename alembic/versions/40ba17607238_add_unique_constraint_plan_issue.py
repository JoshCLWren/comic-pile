"""Enforce one canonical Issue membership per Reading Plan.

A Reading Plan's membership is set membership, so one canonical Issue may
belong to a plan at most once. ``reading_plan_issues`` previously allowed
repeated occurrences of the same ``issue_id`` in one plan, which made
progress, ordering, dependency, and inheritance semantics ambiguous.

Rows written before this constraint existed may already violate it, so the
upgrade collapses them deterministically before adding the constraint: the
occurrence with the lowest ``(display_position, occurrence_id)`` survives. The
collapse preserves intended ordering and dependency semantics instead of
guessing, and moves each removed occurrence's import provenance onto the
survivor. Deployments therefore succeed whether or not duplicates exist.

Revision ID: 40ba17607238
Revises: j1a2b3c4d5e6
Create Date: 2026-10-03 18:39:26.308995
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

CONSTRAINT_NAME = "uq_reading_plan_issue_plan_issue"
_TABLE = "reading_plan_issues"
_DUPLICATE_TABLE = "_rpi_duplicate_occurrences"

_CREATE_DUPLICATES = f"""
CREATE TEMPORARY TABLE {_DUPLICATE_TABLE} AS
SELECT plan_id, issue_id, duplicate_occurrence_id, primary_occurrence_id
FROM (
    SELECT plan_id, issue_id,
           occurrence_id AS duplicate_occurrence_id,
           FIRST_VALUE(occurrence_id) OVER duplicate_partition AS primary_occurrence_id
    FROM {_TABLE}
    WINDOW duplicate_partition AS (
        PARTITION BY plan_id, issue_id ORDER BY display_position, occurrence_id
    )
) AS ranked
WHERE ranked.duplicate_occurrence_id <> ranked.primary_occurrence_id
"""

_DROP_DUPLICATES = f"DROP TABLE {_DUPLICATE_TABLE}"

_PRUNE_REDUNDANT_PLACEMENTS = f"""
DELETE FROM reading_plan_source_placements AS placement
USING (
    SELECT mapped.id AS id,
           ROW_NUMBER() OVER (
               PARTITION BY mapped.plan_id,
                            mapped.target_occurrence_id,
                            mapped.plan_source_id,
                            mapped.source_position
               ORDER BY mapped.id
           ) AS placement_rank
    FROM (
        SELECT placement.id,
               placement.plan_id,
               placement.plan_source_id,
               placement.source_position,
               COALESCE(
                   duplicate.primary_occurrence_id,
                   placement.occurrence_id
               ) AS target_occurrence_id
        FROM reading_plan_source_placements AS placement
        LEFT JOIN {_DUPLICATE_TABLE} AS duplicate
          ON duplicate.plan_id = placement.plan_id
         AND duplicate.duplicate_occurrence_id = placement.occurrence_id
    ) AS mapped
) AS ranked
WHERE placement.id = ranked.id
  AND ranked.placement_rank > 1
"""

_REPOINT_PLACEMENTS = f"""
UPDATE reading_plan_source_placements AS placement
SET occurrence_id = duplicate.primary_occurrence_id
FROM {_DUPLICATE_TABLE} AS duplicate
WHERE placement.plan_id = duplicate.plan_id
  AND placement.occurrence_id = duplicate.duplicate_occurrence_id
"""

_DROP_REMAINING_PLACEMENTS = f"""
DELETE FROM reading_plan_source_placements AS placement
USING {_DUPLICATE_TABLE} AS duplicate
WHERE placement.plan_id = duplicate.plan_id
  AND placement.occurrence_id = duplicate.duplicate_occurrence_id
"""

_DROP_DUPLICATE_MEMBERSHIP = f"""
DELETE FROM {_TABLE} AS membership
USING {_DUPLICATE_TABLE} AS duplicate
WHERE membership.plan_id = duplicate.plan_id
  AND membership.occurrence_id = duplicate.duplicate_occurrence_id
"""

# revision identifiers, used by Alembic.
revision: str = "40ba17607238"
down_revision: str | Sequence[str] | None = "j1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Collapse existing duplicate memberships, then enforce uniqueness.

    The collapse runs first so this migration applies cleanly to a database
    that still holds repeated occurrences, and leaves provenance attached to the
    surviving occurrence instead of orphaned.
    """
    op.execute(_CREATE_DUPLICATES)
    try:
        # Keep one placement per post-collapse (occurrence, source, position)
        # key so the re-point cannot collide with provenance the survivor
        # already owns or with another collapsed occurrence's provenance.
        op.execute(_PRUNE_REDUNDANT_PLACEMENTS)
        op.execute(_REPOINT_PLACEMENTS)
        op.execute(_DROP_REMAINING_PLACEMENTS)
        op.execute(_DROP_DUPLICATE_MEMBERSHIP)
    finally:
        op.execute(_DROP_DUPLICATES)
    op.create_unique_constraint(CONSTRAINT_NAME, _TABLE, ["plan_id", "issue_id"])


def downgrade() -> None:
    """Remove the uniqueness constraint.

    Dropping the constraint cannot restore collapsed rows; the collapse is a
    one-way repair of state that the constraint made illegal.
    """
    op.drop_constraint(CONSTRAINT_NAME, _TABLE, type_="unique")
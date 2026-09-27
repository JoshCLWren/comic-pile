"""Persist proven ContinuityRule semantics as canonical issue Dependency rows.

Revision ID: c86400000001
Revises: d1aa29806941
Create Date: 2026-09-27 04:30:00.000000

Roll eligibility now reads exactly two things: a thread's frontier
(``Thread.next_unread_issue_id``) and that frontier issue's incoming canonical
Dependency rows. ContinuityRule and DependencyGroup ordering are no longer Roll
authorities, so every hard rule that previously existed only as a ContinuityRule
has to be persisted as a canonical edge before the runtime switches. This is
step 1 of the four-step cutover in ``docs/READING_GRAPH_RUNTIME_AUDIT.md``.

Only the two rule forms that exist in production are converted:

* ``item_read`` (``A -> B``) becomes ``Dependency(A, B)``;
* ``converged`` on target ``D`` with prerequisites ``[B, C]`` becomes
  ``Dependency(B, D)`` and ``Dependency(C, D)``, which is lossless because
  multiple incoming dependencies already require every prerequisite.

Edges that already exist are left alone, so the migration is idempotent and no
existing Dependency or ContinuityRule row is modified or deleted. Historical
``cbl-order:%`` materialization is untouched and stays inert: new rows carry a
``canonical-from-rule:<rule id>`` note, which the canonical predicate in
``comic_pile.dependencies`` accepts and which joins back to the originating
Reading-Plan-owned rule for attribution.

The ``dependencies`` -> ``continuity_rule`` mirroring trigger is suspended for
the insert so it cannot rewrite an existing rule's ``continuity-plan:<id>``
marker, which Reading Plan cleanup relies on. The suspension is part of the same
transaction, so a failure rolls it back.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "c86400000001"
down_revision: str | Sequence[str] | None = "d1aa29806941"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SYNC_TRIGGER = "trg_sync_legacy_dependency_to_continuity_rule"
CANONICAL_NOTE_PREFIX = "canonical-from-rule:"

# Rule-native item_read edges: one canonical Dependency per missing hard edge.
PERSIST_ITEM_READ_EDGES_SQL = f"""
INSERT INTO dependencies (source_issue_id, target_issue_id, note, created_at)
SELECT rule.source_id,
       rule.target_id,
       '{CANONICAL_NOTE_PREFIX}' || rule.id,
       COALESCE(rule.created_at, CURRENT_TIMESTAMP)
  FROM continuity_rules AS rule
  JOIN issues AS source_issue ON source_issue.id = rule.source_id
  JOIN threads AS source_thread ON source_thread.id = source_issue.thread_id
  JOIN issues AS target_issue ON target_issue.id = rule.target_id
  JOIN threads AS target_thread ON target_thread.id = target_issue.thread_id
 WHERE rule.source_type = 'issue'
   AND rule.target_type = 'issue'
   AND rule.satisfaction_type = 'item_read'
   AND rule.checkpoint_issue_id IS NULL
   AND source_thread.user_id = rule.user_id
   AND target_thread.user_id = rule.user_id
   AND NOT EXISTS (
        SELECT 1
          FROM dependencies AS existing
         WHERE existing.source_issue_id = rule.source_id
           AND existing.target_issue_id = rule.target_id
       )
ON CONFLICT (source_issue_id, target_issue_id) DO NOTHING
"""

# Converged rules are not primitives under the frozen architecture: each
# convergence prerequisite becomes its own incoming canonical edge.
PERSIST_CONVERGED_EDGES_SQL = f"""
INSERT INTO dependencies (source_issue_id, target_issue_id, note, created_at)
SELECT prerequisite.issue_id,
       rule.target_id,
       '{CANONICAL_NOTE_PREFIX}' || rule.id,
       COALESCE(rule.created_at, CURRENT_TIMESTAMP)
  FROM continuity_rules AS rule
  CROSS JOIN LATERAL (
        SELECT CASE
                   WHEN entry.value->>'id' ~ '^[0-9]{{1,9}}$'
                   THEN (entry.value->>'id')::integer
               END AS issue_id
          FROM json_array_elements(rule.convergence_targets) AS entry(value)
         WHERE entry.value->>'type' = 'issue'
       ) AS prerequisite
  JOIN issues AS source_issue ON source_issue.id = prerequisite.issue_id
  JOIN threads AS source_thread ON source_thread.id = source_issue.thread_id
  JOIN issues AS target_issue ON target_issue.id = rule.target_id
  JOIN threads AS target_thread ON target_thread.id = target_issue.thread_id
 WHERE rule.satisfaction_type = 'converged'
   AND rule.convergence_targets IS NOT NULL
   AND prerequisite.issue_id IS NOT NULL
   AND prerequisite.issue_id <> rule.target_id
   AND source_thread.user_id = rule.user_id
   AND target_thread.user_id = rule.user_id
   AND NOT EXISTS (
        SELECT 1
          FROM dependencies AS existing
         WHERE existing.source_issue_id = prerequisite.issue_id
           AND existing.target_issue_id = rule.target_id
       )
ON CONFLICT (source_issue_id, target_issue_id) DO NOTHING
"""

DELETE_CANONICAL_EDGES_SQL = f"""
DELETE FROM dependencies
 WHERE note LIKE '{CANONICAL_NOTE_PREFIX}%'
"""

# Suspend the legacy mirroring trigger only when it is actually present, so this
# migration also applies to databases that already dropped it.
SUSPEND_MIRRORING_TRIGGER_SQL = f"""
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM pg_trigger
         WHERE tgname = '{_SYNC_TRIGGER}'
           AND NOT tgisinternal
    ) THEN
        EXECUTE 'ALTER TABLE dependencies DISABLE TRIGGER {_SYNC_TRIGGER}';
    END IF;
END
$$
"""

RESUME_MIRRORING_TRIGGER_SQL = f"""
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM pg_trigger
         WHERE tgname = '{_SYNC_TRIGGER}'
           AND NOT tgisinternal
    ) THEN
        EXECUTE 'ALTER TABLE dependencies ENABLE TRIGGER {_SYNC_TRIGGER}';
    END IF;
END
$$
"""


def upgrade() -> None:
    """Persist canonical Dependency rows for every proven hard ContinuityRule."""
    op.execute(sa.text(SUSPEND_MIRRORING_TRIGGER_SQL))
    op.execute(sa.text(PERSIST_ITEM_READ_EDGES_SQL))
    op.execute(sa.text(PERSIST_CONVERGED_EDGES_SQL))
    op.execute(sa.text(RESUME_MIRRORING_TRIGGER_SQL))


def downgrade() -> None:
    """Remove only the canonical edges this migration created."""
    op.execute(sa.text(DELETE_CANONICAL_EDGES_SQL))

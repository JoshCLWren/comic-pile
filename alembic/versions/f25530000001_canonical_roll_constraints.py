"""Backfill proven canonical hard constraints and retire the reverse rule bridge.

Revision ID: f25530000001
Revises: e913be4e091d

The cutover preserves historical CBL rows as inert provenance. Issue-level
item_read/checkpoint/convergence authoring intent becomes canonical Dependencies;
normal forward progression within a Thread needs no additional edge.
"""

from collections.abc import Sequence
import importlib.util
from pathlib import Path

from alembic import op
import sqlalchemy as sa

revision: str = "f25530000001"
down_revision: str | Sequence[str] | None = "e913be4e091d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# A transaction-local staging table keeps the reviewed authoring provenance
# separate from inserted Dependencies. No replacement runtime graph survives.
PAIRS_SQL = """
CREATE TEMP TABLE canonical_cutover_pairs ON COMMIT DROP AS
WITH hard_rules AS (
    SELECT * FROM continuity_rules
    WHERE target_type = 'issue'
      AND (note IS NULL OR note NOT LIKE 'cbl-order:%')
), expanded AS (
    SELECT user_id, source_id AS source_issue_id, target_id AS target_issue_id, note
      FROM hard_rules WHERE source_type = 'issue' AND satisfaction_type = 'item_read'
    UNION
    SELECT user_id, checkpoint_issue_id, target_id, note
      FROM hard_rules WHERE satisfaction_type = 'checkpoint' AND checkpoint_issue_id IS NOT NULL
    UNION
    SELECT rule.user_id, (gate.value->>'id')::integer, rule.target_id, rule.note
      FROM hard_rules AS rule
      CROSS JOIN LATERAL json_array_elements(COALESCE(rule.convergence_targets, '[]'::json)) AS gate(value)
     WHERE rule.satisfaction_type = 'converged' AND gate.value->>'type' = 'issue'
)
SELECT DISTINCT expanded.*, source.thread_id AS source_thread_id,
       target.thread_id AS target_thread_id, source.position AS source_position,
       target.position AS target_position, source_thread.user_id AS source_user_id,
       target_thread.user_id AS target_user_id
  FROM expanded
  LEFT JOIN issues AS source ON source.id = expanded.source_issue_id
  LEFT JOIN threads AS source_thread ON source_thread.id = source.thread_id
  LEFT JOIN issues AS target ON target.id = expanded.target_issue_id
  LEFT JOIN threads AS target_thread ON target_thread.id = target.thread_id

"""


def upgrade() -> None:
    """Compile proven hard pairs before the canonical-only runtime is deployed."""
    op.execute(
        sa.text(
            "DROP TRIGGER IF EXISTS trg_sync_legacy_dependency_to_continuity_rule ON dependencies"
        )
    )
    op.execute(sa.text("DROP FUNCTION IF EXISTS sync_legacy_dependency_to_continuity_rule()"))
    op.execute(
        sa.text("""
        DO $$ BEGIN
          IF EXISTS (
            SELECT 1 FROM continuity_rules AS rule
            WHERE (note IS NULL OR note NOT LIKE 'cbl-order:%')
              AND (target_type <> 'issue'
                OR satisfaction_type NOT IN ('item_read', 'checkpoint', 'converged')
                OR (satisfaction_type = 'item_read' AND source_type <> 'issue')
                OR (satisfaction_type = 'checkpoint' AND checkpoint_issue_id IS NULL)
                OR (satisfaction_type = 'converged' AND EXISTS (
                    SELECT 1 FROM json_array_elements(COALESCE(convergence_targets, '[]'::json)) AS gate(value)
                    WHERE gate.value->>'type' <> 'issue'
                )))
          ) THEN
            RAISE EXCEPTION 'Canonical cutover requires reviewed Issue mappings for unsupported hard rules';
          END IF;
        END $$
    """)
    )
    op.execute(sa.text(PAIRS_SQL))
    op.execute(
        sa.text("""
        DO $$ BEGIN
          IF EXISTS (
            SELECT 1 FROM canonical_cutover_pairs
            WHERE source_user_id IS DISTINCT FROM user_id
               OR target_user_id IS DISTINCT FROM user_id
               OR source_issue_id = target_issue_id
          ) THEN
            RAISE EXCEPTION 'Canonical cutover found missing, unowned, or self-referential hard Issues';
          END IF;
        END $$
    """)
    )
    op.execute(
        sa.text("""
        DELETE FROM canonical_cutover_pairs
        WHERE source_thread_id = target_thread_id AND source_position < target_position
    """)
    )
    op.execute(
        sa.text("""
        INSERT INTO dependencies (source_issue_id, target_issue_id, note, created_at)
        SELECT DISTINCT source_issue_id, target_issue_id,
               'canonical:compiled-hard-constraint', CURRENT_TIMESTAMP
          FROM canonical_cutover_pairs
        ON CONFLICT (source_issue_id, target_issue_id) DO UPDATE
          SET note = EXCLUDED.note
          WHERE dependencies.note LIKE 'cbl-order:%'
    """)
    )
    op.execute(
        sa.text("""
        INSERT INTO reading_plan_dependencies (plan_id, dependency_id, explanation)
        SELECT DISTINCT plan.id, dependency.id, 'Compiled hard constraint'
          FROM canonical_cutover_pairs AS pair
          JOIN continuity_plans AS plan
            ON pair.note = 'continuity-plan:' || plan.id::text AND pair.user_id = plan.user_id
          JOIN dependencies AS dependency
            ON dependency.source_issue_id = pair.source_issue_id
           AND dependency.target_issue_id = pair.target_issue_id
        ON CONFLICT DO NOTHING
    """)
    )
    op.execute(
        sa.text("""
        UPDATE threads AS target_thread SET is_blocked = EXISTS (
            SELECT 1 FROM dependencies AS dependency
            JOIN issues AS source ON source.id = dependency.source_issue_id
            LEFT JOIN threads AS source_thread ON source_thread.id = source.thread_id
            LEFT JOIN issues AS target ON target.id = dependency.target_issue_id
            WHERE target.id = target_thread.next_unread_issue_id
              AND target.thread_id = target_thread.id
              AND source_thread.user_id = target_thread.user_id
              AND source.status <> 'read'
              AND (dependency.note IS NULL OR dependency.note NOT LIKE 'cbl-order:%')
        )
    """)
    )


def downgrade() -> None:
    """Restore the compatibility bridge without deleting canonical reader intent.

    Shared new-only authoring cannot be represented by the old single-owner
    rule model. Refuse that reversal; use a forward fix in that case.
    """
    shared = op.get_bind().scalar(
        sa.text("""
        SELECT EXISTS (
            SELECT dependency_id FROM reading_plan_dependencies
            GROUP BY dependency_id HAVING count(*) > 1
        )
    """)
    )
    if shared:
        raise RuntimeError(
            "Shared canonical constraints require a forward fix; legacy downgrade is unsafe"
        )
    spec = importlib.util.spec_from_file_location(
        "legacy_dependency_bridge",
        Path(__file__).with_name("c84400000002_sync_legacy_dependency_writes.py"),
    )
    assert spec is not None and spec.loader is not None
    previous = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(previous)
    previous.upgrade()

"""Cut over Roll eligibility to Thread frontier plus canonical issue Dependencies.

Revision ID: cutover-2553
Revises: g9h0i1j2k3l4
Create Date: 2026-09-28 00:00:00.000000

Persists canonical Dependency rows derived from proven hard
ContinuityRules: rule-native item_read rules and converged
prerequisite edges. Historical cbl-order:% rows remain inert.

Also drops the trigger that mirrored Dependency writes into
ContinuityRules since the Dependency table is now canonical.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "cutover-2553"
# Down revision is the previous migration
# NOTE: revision string contains hyphen, acceptable
# for alembic

down_revision: str | Sequence[str] | None = "g9h0i1j2k3l4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist canonical Dependency edges and drop legacy bridge trigger."""
    # Insert canonical Dependency rows for rule-native item_read rules that have no existing matching Dependency row.
    op.execute(
        sa.text(
            """
            INSERT INTO dependencies (source_issue_id, target_issue_id, note, created_at)
            SELECT DISTINCT ON (dcr.source_issue_id, dcr.target_issue_id)
                dcr.source_issue_id,
                dcr.target_issue_id,
                'canonical:' || dcr.rule_id,
                dcr.created_at
            FROM (
                SELECT cr.id AS rule_id,
                       cr.source_id AS source_issue_id,
                       cr.target_id AS target_issue_id,
                       cr.created_at
                FROM continuity_rules cr
                WHERE cr.satisfaction_type = 'item_read'
                  AND cr.source_type = 'issue'
                  AND cr.target_type = 'issue'
                  AND cr.checkpoint_issue_id IS NULL
                  AND cr.convergence_targets IS NULL
            ) dcr
            LEFT JOIN dependencies d
                ON d.source_issue_id = dcr.source_issue_id
                AND d.target_issue_id = dcr.target_issue_id
            WHERE d.id IS NULL
            ORDER BY dcr.source_issue_id, dcr.target_issue_id, dcr.created_at DESC
            ON CONFLICT (source_issue_id, target_issue_id) DO NOTHING;
            """
        )
    )

    # Insert canonical Dependency rows for converged rules: one edge per convergence target that has no existing matching Dependency row.
    op.execute(
        sa.text(
            """
            INSERT INTO dependencies (source_issue_id, target_issue_id, note, created_at)
            SELECT DISTINCT ON (src_issue.id, (tgt->>'id')::int)
                src_issue.id,
                (tgt->>'id')::int,
                'canonical:' || cr.id,
                cr.created_at
            FROM continuity_rules cr
            JOIN issues src_issue ON src_issue.id = cr.source_id
            CROSS JOIN jsonb_array_elements(
                CASE WHEN cr.convergence_targets::text <> 'null'
                      AND cr.convergence_targets IS NOT NULL
                      THEN cr.convergence_targets::jsonb
                      ELSE '[]'::jsonb
                END
            ) AS tgt
            JOIN issues tgt_issue ON tgt_issue.id = (tgt->>'id')::int
            LEFT JOIN dependencies d
                ON d.source_issue_id = src_issue.id
                AND d.target_issue_id = tgt_issue.id
            WHERE cr.satisfaction_type = 'converged'
              AND src_issue.id <> (tgt->>'id')::int
              AND d.id IS NULL
            ORDER BY src_issue.id, (tgt->>'id')::int, cr.created_at DESC
            ON CONFLICT (source_issue_id, target_issue_id) DO NOTHING;
            """
        )
    )

    # Drop the trigger that mirrored Dependency writes into ContinuityRules.
    op.execute("DROP TRIGGER IF EXISTS trg_sync_legacy_dependency_to_continuity_rule ON dependencies")


def downgrade() -> None:
    """Revert the cutover by removing canonical Dependency rows."""
    op.execute(
        sa.text(
            """
            DELETE FROM dependencies
            WHERE note LIKE 'canonical:%'
            """
        )
    )

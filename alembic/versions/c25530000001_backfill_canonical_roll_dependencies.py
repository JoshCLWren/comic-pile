"""Backfill canonical issue Dependencies from ContinuityRules for the Roll cutover (#2553).

Revision ID: c25530000001
Revises: e913be4e091d
Create Date: 2026-10-10

Cutover data step for #2553 (frozen architecture: docs/READING_GRAPH_ADR.md,
docs/READING_GRAPH_RUNTIME_AUDIT.md section 7 step 1):

1. Validates that every rule-native ContinuityRule (no legacy_dependency_id
   mirror) compiles to issue-level Dependency edges. Anything that cannot
   compile aborts the migration with the offending rule IDs instead of
   silently dropping constraints.
2. Drops the Dependency -> ContinuityRule mirroring trigger before the
   backfill so backfilled edges are not claimed back into mirrored rules.
3. Persists one canonical Dependency edge per rule-native item_read rule and
   one per converged prerequisite. Historical ``cbl-order:%`` rows are never
   touched; they stay inert via the evaluator's note predicate.
4. Links each backfilled edge to its owning Reading Plan through
   reading_plan_dependencies, but only when the plan exists and is owned by
   the same user as the rule. Cross-user note references are skipped and
   reported, never blindly translated.

The heavy lifting lives in app.services.canonical_backfill so it is unit
testable without an Alembic context.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op

from app.services.canonical_backfill import (
    EDGE_NOTE_PREFIX,
    backfill_converged_edges,
    backfill_item_read_edges,
    drop_mirror_trigger,
    link_plan_provenance,
    validate_compilable_rules,
)

# revision identifiers, used by Alembic.
revision: str = "c25530000001"
down_revision: str | Sequence[str] | None = "f2a3b4c5d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Validate, drop the mirror trigger, backfill canonical edges, link plans."""
    bind = op.get_bind()

    validate_compilable_rules(bind)
    drop_mirror_trigger(bind)

    item_inserted, item_existing = backfill_item_read_edges(bind)
    conv_inserted, conv_existing, conv_self_skipped = backfill_converged_edges(bind)
    links_created, links_skipped = link_plan_provenance(bind)

    print(f"[c25530000001] item_read edges: {item_inserted} inserted, {item_existing} already present")
    print(
        f"[c25530000001] converged edges: {conv_inserted} inserted, "
        f"{conv_existing} already present, {conv_self_skipped} self-edges skipped"
    )
    print(f"[c25530000001] reading_plan_dependencies links created: {links_created}")
    if links_skipped:
        print(f"[c25530000001] WARNING: {len(links_skipped)} plan links skipped (not translated):")
        for rule_id, reason in links_skipped:
            print(f"[c25530000001]   rule {rule_id}: {reason}")


def downgrade() -> None:
    """Remove backfilled edges and restore the mirror trigger."""
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM dependencies WHERE note LIKE :pattern"),
        {"pattern": f"{EDGE_NOTE_PREFIX}%"},
    )
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import c84400000002_sync_legacy_dependency_writes as trigger_migration

    trigger_migration.upgrade()

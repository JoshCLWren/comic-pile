"""Backfill canonical issue Dependencies from ContinuityRules for the Roll cutover (#2553).

Revision ID: c25530000001
Revises: m5d300000001
Create Date: 2026-10-10

Cutover data step for #2553 (frozen architecture: docs/READING_GRAPH_ADR.md,
docs/READING_GRAPH_RUNTIME_AUDIT.md section 7 step 1):

1. Validates that every rule-native ContinuityRule (no legacy_dependency_id
   mirror) compiles to issue-level Dependency edges, and that those edges
   plus existing canonical Dependencies do not form a cycle. A reviewed
   allowlist of six test-user ContinuityRule ids may dangle: those rows
   are reported (owner, rule id, missing issue ids, missing side) and left
   unchanged. Any other dangling rule — especially a user-owned
   prerequisite — aborts with an investigation-grade error. Cycles,
   non-issue endpoints, cross-user references, and unhandled types still
   abort with the offending rule IDs.
2. Drops the Dependency -> ContinuityRule mirroring trigger before the
   backfill so backfilled edges are not claimed back into mirrored rules.
3. Persists one canonical Dependency edge per rule-native item_read rule and
   one per converged prerequisite. Historical ``cbl-order:%`` rows are never
   touched; they stay inert via the evaluator's note predicate.
4. Links each backfilled edge to its owning Reading Plan through
   reading_plan_dependencies, but only when the plan exists and is owned by
   the same user as the rule. Cross-user / missing plan notes are skipped
   and reported. Allowlisted dangling item_read rows are skipped the same
   way; any other missing endpoint aborts.

The heavy lifting lives in app.services.canonical_backfill so it is unit
testable without an Alembic context.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from alembic import op

from app.services.canonical_backfill import (
    DanglingRuleReport,
    abort_on_retired_list_chain_rules,
    backfill_converged_edges,
    backfill_item_read_edges,
    drop_mirror_trigger,
    link_plan_provenance,
    revert_backfilled_edges,
    validate_compilable_rules,
)

# revision identifiers, used by Alembic.
revision: str = "c25530000001"
down_revision: str | Sequence[str] | None = "m5d300000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _print_dangling_skipped(skipped: list[DanglingRuleReport]) -> None:
    """Report each reviewed dangling skip with owner, rule, issues, and side."""
    if not skipped:
        return
    print(
        f"[c25530000001] WARNING: {len(skipped)} reviewed dangling rule(s) "
        "skipped (left unchanged, not compiled):"
    )
    for row in skipped:
        print(f"[c25530000001]   {row.report()}")


def _print_skipped(kind: str, skipped: list[tuple[int, str]]) -> None:
    """Report skipped plan-note translations."""
    if not skipped:
        return
    print(f"[c25530000001] WARNING: {len(skipped)} {kind}:")
    for rule_id, reason in skipped:
        print(f"[c25530000001]   rule {rule_id}: {reason}")


def upgrade() -> None:
    """Validate, drop the mirror trigger, backfill canonical edges, link plans."""
    bind = op.get_bind()

    # Preflight (before any writes): retired same-thread list-chain rules must
    # abort the replay per docs/roll-eligibility-contract.md.
    abort_on_retired_list_chain_rules(bind)
    skipped_dangling = validate_compilable_rules(bind)
    drop_mirror_trigger(bind)

    item_inserted, item_existing = backfill_item_read_edges(bind)
    conv_inserted, conv_existing, conv_self_skipped = backfill_converged_edges(bind)
    links_created, links_skipped = link_plan_provenance(bind)

    _print_dangling_skipped(skipped_dangling)
    print(f"[c25530000001] item_read edges: {item_inserted} inserted, {item_existing} already present")
    print(
        f"[c25530000001] converged edges: {conv_inserted} inserted, "
        f"{conv_existing} already present, {conv_self_skipped} self-edges skipped"
    )
    print(f"[c25530000001] reading_plan_dependencies links created: {links_created}")
    _print_skipped("plan links skipped (not translated)", links_skipped)


def downgrade() -> None:
    """Remove backfilled edges only and restore the mirror trigger.

    Live ``canonical:rule:<id>`` edges authored after the upgrade are kept,
    including their ``reading_plan_dependencies`` provenance links.
    """
    bind = op.get_bind()
    revert_backfilled_edges(bind)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import c84400000002_sync_legacy_dependency_writes as trigger_migration

    trigger_migration.upgrade()

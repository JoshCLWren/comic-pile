"""Backfill canonical issue Dependencies from ContinuityRules (#2553).

Data-migration logic for the Roll cutover: validates that every rule-native
ContinuityRule compiles to issue-level edges, persists those edges, and links
them to their owning Reading Plans with ownership validation. The Alembic
migration ``c25530000001`` is a thin wrapper around these functions.
"""

from __future__ import annotations

import json
import re

import sqlalchemy as sa
from sqlalchemy.engine import Connection

EDGE_NOTE_PREFIX = "canonical:rule-backfill:"
_PLAN_NOTE_RE = re.compile(r"^continuity-plan:(\d+)$")
_MAX_REPORTED_IDS = 50


def abort_with_rule_ids(rule_ids: list[int], reason: str) -> None:
    """Abort the migration with an actionable error listing the bad rules."""
    shown = ", ".join(str(i) for i in sorted(rule_ids)[:_MAX_REPORTED_IDS])
    extra = (
        f" (and {len(rule_ids) - _MAX_REPORTED_IDS} more)"
        if len(rule_ids) > _MAX_REPORTED_IDS
        else ""
    )
    raise RuntimeError(
        f"Cannot backfill canonical Dependencies: {len(rule_ids)} rule(s) {reason}: "
        f"{shown}{extra}. Resolve or remove these rules, then re-run the migration."
    )


def validate_compilable_rules(bind: Connection) -> None:
    """Ensure every rule-native ContinuityRule reduces to issue-level edges."""
    native = "legacy_dependency_id IS NULL"

    bad_types = [
        row[0]
        for row in bind.execute(
            sa.text(
                "SELECT id FROM continuity_rules "
                f"WHERE {native} AND satisfaction_type NOT IN ('item_read', 'converged')"
            )
        ).all()
    ]
    if bad_types:
        abort_with_rule_ids(bad_types, "have unhandled satisfaction_type values")

    non_issue = [
        row[0]
        for row in bind.execute(
            sa.text(
                "SELECT id FROM continuity_rules "
                f"WHERE {native} AND satisfaction_type = 'item_read' "
                "AND (source_type <> 'issue' OR target_type <> 'issue')"
            )
        ).all()
    ]
    if non_issue:
        abort_with_rule_ids(non_issue, "are item_read rules with non-issue endpoints")

    dangling = [
        row[0]
        for row in bind.execute(
            sa.text(
                "SELECT r.id FROM continuity_rules r "
                "LEFT JOIN issues s ON s.id = r.source_id "
                "LEFT JOIN issues t ON t.id = r.target_id "
                f"WHERE r.{native} AND r.satisfaction_type = 'item_read' "
                "AND (s.id IS NULL OR t.id IS NULL)"
            )
        ).all()
    ]
    if dangling:
        abort_with_rule_ids(dangling, "reference missing source or target issues")

    cross_user = [
        row[0]
        for row in bind.execute(
            sa.text(
                "SELECT r.id FROM continuity_rules r "
                "JOIN issues s ON s.id = r.source_id "
                "JOIN issues t ON t.id = r.target_id "
                "JOIN threads st ON st.id = s.thread_id "
                "JOIN threads tt ON tt.id = t.thread_id "
                f"WHERE r.{native} AND r.satisfaction_type = 'item_read' "
                "AND (st.user_id <> r.user_id OR tt.user_id <> r.user_id)"
            )
        ).all()
    ]
    if cross_user:
        abort_with_rule_ids(cross_user, "reference issues owned by a different user than the rule")

    bad_converged_target = [
        row[0]
        for row in bind.execute(
            sa.text(
                "SELECT r.id FROM continuity_rules r "
                "LEFT JOIN issues t ON t.id = r.target_id "
                "LEFT JOIN threads tt ON tt.id = t.thread_id "
                f"WHERE r.{native} AND r.satisfaction_type = 'converged' "
                "AND (r.target_type <> 'issue' OR t.id IS NULL OR tt.user_id <> r.user_id)"
            )
        ).all()
    ]
    if bad_converged_target:
        abort_with_rule_ids(
            bad_converged_target,
            "are converged rules with a non-issue, missing, or cross-user target",
        )

    bad_prereq = [
        row[0]
        for row in bind.execute(
            sa.text(
                # NB: the issues join compares on text so a malformed id is
                # reported by this validation instead of raising a cast error.
                "SELECT DISTINCT r.id FROM continuity_rules r, "
                "LATERAL json_array_elements(r.convergence_targets) AS elem "
                "LEFT JOIN issues i ON i.id::text = elem->>'id' "
                "LEFT JOIN threads th ON th.id = i.thread_id "
                f"WHERE r.{native} AND r.satisfaction_type = 'converged' "
                "AND (elem->>'id' !~ '^[0-9]+$' OR elem->>'type' <> 'issue' "
                "OR i.id IS NULL OR th.user_id <> r.user_id)"
            )
        ).all()
    ]
    if bad_prereq:
        abort_with_rule_ids(
            bad_prereq,
            "have convergence prerequisites that are not existing issues "
            "owned by the rule's user",
        )


def drop_mirror_trigger(bind: Connection) -> None:
    """Remove the Dependency -> ContinuityRule compatibility bridge."""
    bind.execute(sa.text("DROP TRIGGER IF EXISTS trg_sync_legacy_dependency_to_continuity_rule ON dependencies"))
    bind.execute(sa.text("DROP FUNCTION IF EXISTS sync_legacy_dependency_to_continuity_rule()"))


def backfill_item_read_edges(bind: Connection) -> tuple[int, int]:
    """Persist one edge per rule-native item_read rule. Returns (inserted, skipped_existing)."""
    before = bind.execute(sa.text("SELECT COUNT(*) FROM dependencies")).scalar_one()
    bind.execute(
        sa.text(
            "INSERT INTO dependencies (source_issue_id, target_issue_id, note, created_at) "
            "SELECT r.source_id, r.target_id, "
            f"'{EDGE_NOTE_PREFIX}' || r.id, now() "
            "FROM continuity_rules r "
            "WHERE r.legacy_dependency_id IS NULL "
            "AND r.satisfaction_type = 'item_read' "
            "ON CONFLICT (source_issue_id, target_issue_id) DO NOTHING"
        )
    )
    after = bind.execute(sa.text("SELECT COUNT(*) FROM dependencies")).scalar_one()
    distinct_pairs = bind.execute(
        sa.text(
            "SELECT COUNT(DISTINCT (source_id, target_id)) FROM continuity_rules "
            "WHERE legacy_dependency_id IS NULL AND satisfaction_type = 'item_read'"
        )
    ).scalar_one()
    inserted = after - before
    return inserted, distinct_pairs - inserted


def backfill_converged_edges(bind: Connection) -> tuple[int, int, int]:
    """Expand converged rules into per-prerequisite edges. Returns (inserted, skipped_existing, skipped_self)."""
    self_edges = bind.execute(
        sa.text(
            "SELECT COUNT(DISTINCT (elem->>'id')::int) FROM continuity_rules r, "
            "LATERAL json_array_elements(r.convergence_targets) AS elem "
            "WHERE r.legacy_dependency_id IS NULL "
            "AND r.satisfaction_type = 'converged' "
            "AND (elem->>'id')::int = r.target_id"
        )
    ).scalar_one()
    before = bind.execute(sa.text("SELECT COUNT(*) FROM dependencies")).scalar_one()
    bind.execute(
        sa.text(
            "INSERT INTO dependencies (source_issue_id, target_issue_id, note, created_at) "
            "SELECT DISTINCT (elem->>'id')::int, r.target_id, "
            f"'{EDGE_NOTE_PREFIX}' || r.id, now() "
            "FROM continuity_rules r, "
            "LATERAL json_array_elements(r.convergence_targets) AS elem "
            "WHERE r.legacy_dependency_id IS NULL "
            "AND r.satisfaction_type = 'converged' "
            "AND (elem->>'id')::int <> r.target_id "
            "ON CONFLICT (source_issue_id, target_issue_id) DO NOTHING"
        )
    )
    after = bind.execute(sa.text("SELECT COUNT(*) FROM dependencies")).scalar_one()
    prereq_count = bind.execute(
        sa.text(
            "SELECT COUNT(DISTINCT ((elem->>'id')::int, r.target_id)) "
            "FROM continuity_rules r, "
            "LATERAL json_array_elements(r.convergence_targets) AS elem "
            "WHERE r.legacy_dependency_id IS NULL "
            "AND r.satisfaction_type = 'converged' "
            "AND (elem->>'id')::int <> r.target_id"
        )
    ).scalar_one()
    inserted = after - before
    return inserted, prereq_count - inserted, self_edges


def rule_edge_pairs(
    satisfaction_type: str,
    source_id: int,
    target_id: int,
    convergence_targets: object,
) -> list[tuple[int, int]]:
    """Recompute the canonical edge pairs a rule compiles to (mirrors the backfill)."""
    if satisfaction_type == "item_read":
        return [(source_id, target_id)]
    raw_targets: object = convergence_targets or []
    if isinstance(raw_targets, str):
        raw_targets = json.loads(raw_targets)
    targets: list[dict[str, object]] = raw_targets if isinstance(raw_targets, list) else []
    pairs: list[tuple[int, int]] = []
    for target_info in targets:
        raw_id = target_info["id"]
        if not isinstance(raw_id, (int, str)):
            continue
        prereq_id = int(raw_id)
        if prereq_id != target_id:  # self-edges are never persisted
            pairs.append((prereq_id, target_id))
    return pairs


def link_plan_provenance(bind: Connection) -> tuple[int, list[tuple[int, str]]]:
    """Link backfilled edges to their owning plans with ownership validation.

    Edges are resolved by (source, target) issue pair rather than by backfill
    note so that several rules compiling to the same edge each get their plan
    link. Returns (links_created, skipped) where skipped is a list of
    (rule_id, reason) for plan notes that could not be safely translated.
    """
    links_created = 0
    skipped: list[tuple[int, str]] = []
    plan_rules = bind.execute(
        sa.text(
            "SELECT id, user_id, note, satisfaction_type, source_id, target_id, "
            "convergence_targets FROM continuity_rules "
            "WHERE legacy_dependency_id IS NULL "
            "AND satisfaction_type IN ('item_read', 'converged') "
            "AND note ~ '^continuity-plan:[0-9]+$'"
        )
    ).all()
    for rule in plan_rules:
        rule_id, user_id, note, satisfaction_type, source_id, target_id, convergence_targets = rule
        match = _PLAN_NOTE_RE.match(note or "")
        if match is None:
            skipped.append((rule_id, f"unparseable plan note {note!r}"))
            continue
        plan_id = int(match.group(1))
        plan_owner = bind.execute(
            sa.text("SELECT user_id FROM continuity_plans WHERE id = :plan_id"),
            {"plan_id": plan_id},
        ).scalar_one_or_none()
        if plan_owner is None:
            skipped.append((rule_id, f"plan {plan_id} does not exist"))
            continue
        if plan_owner != user_id:
            skipped.append(
                (rule_id, f"plan {plan_id} is owned by user {plan_owner}, not rule owner {user_id}")
            )
            continue
        pairs = rule_edge_pairs(satisfaction_type, source_id, target_id, convergence_targets)
        for src_id, tgt_id in pairs:
            result = bind.execute(
                sa.text(
                    "INSERT INTO reading_plan_dependencies (plan_id, dependency_id, explanation) "
                    "SELECT :plan_id, d.id, :explanation FROM dependencies d "
                    "WHERE d.source_issue_id = :src AND d.target_issue_id = :tgt "
                    "ON CONFLICT DO NOTHING"
                ),
                {"plan_id": plan_id, "explanation": note, "src": src_id, "tgt": tgt_id},
            )
            links_created += result.rowcount
    return links_created, skipped



"""Backfill canonical issue Dependencies from ContinuityRules (#2553).

Data-migration logic for the Roll cutover: validates that every rule-native
ContinuityRule compiles to issue-level edges, persists those edges, and links
them to their owning Reading Plans with ownership validation. The Alembic
migration ``c25530000001`` is a thin wrapper around these functions.

Dangling source/target issues abort the migration except for a reviewed
allowlist of six test-user ContinuityRule ids. Those rows are reported with
owner, rule id, missing issue ids, and missing side, then left unchanged.
Any other dangling rule — especially a real user's prerequisite — aborts
with an investigation-grade error. Cycles, non-issue endpoints, cross-user
references, and unhandled types still abort.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict, deque
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.engine import Connection

# Live writes use EDGE_NOTE_PREFIX; this backfill uses a distinct prefix so
# Alembic downgrade can revert only the rows it inserted. Retirement matches
# both prefixes via rule_compiled_note_filter().
from app.services.canonical_constraint_compiler import BACKFILL_EDGE_NOTE_PREFIX

logger = logging.getLogger(__name__)

_PLAN_NOTE_RE = re.compile(r"^continuity-plan:(\d+)$")
_MAX_REPORTED_IDS = 50
_NATIVE = "legacy_dependency_id IS NULL"
_ITEM_READ_ENDPOINTS_EXIST = (
    "EXISTS (SELECT 1 FROM issues s WHERE s.id = r.source_id) "
    "AND EXISTS (SELECT 1 FROM issues t WHERE t.id = r.target_id)"
)

# Reviewed 2026-10-12 production finding: these six item_read rules are the
# only dangling ContinuityRules in prod. All are owned by test user 23199.
# Any other missing-endpoint rule must abort rather than drop a prerequisite.
REVIEWED_DANGLING_OWNER_USER_ID = 23199
DANGLING_RULE_ALLOWLIST: frozenset[tuple[int, int]] = frozenset(
    {
        (1715192, REVIEWED_DANGLING_OWNER_USER_ID),
        (1715241, REVIEWED_DANGLING_OWNER_USER_ID),
        (1715291, REVIEWED_DANGLING_OWNER_USER_ID),
        (1715333, REVIEWED_DANGLING_OWNER_USER_ID),
        (1715578, REVIEWED_DANGLING_OWNER_USER_ID),
        (1715620, REVIEWED_DANGLING_OWNER_USER_ID),
    }
)


@dataclass(frozen=True)
class DanglingRuleReport:
    """One dangling ContinuityRule, with enough detail to investigate or skip."""

    rule_id: int
    user_id: int
    source_id: int
    target_id: int
    missing_source: bool
    missing_target: bool

    def missing_sides(self) -> list[str]:
        """Return which endpoint sides no longer exist."""
        sides: list[str] = []
        if self.missing_source:
            sides.append("source")
        if self.missing_target:
            sides.append("target")
        return sides

    def missing_issue_ids(self) -> list[int]:
        """Return the issue ids that no longer exist."""
        missing: list[int] = []
        if self.missing_source:
            missing.append(self.source_id)
        if self.missing_target:
            missing.append(self.target_id)
        return missing

    def report(self) -> str:
        """Return an investigation-grade one-line description of this row."""
        sides = " and ".join(self.missing_sides()) or "unknown"
        ids = ", ".join(str(issue_id) for issue_id in self.missing_issue_ids())
        return (
            f"user_id={self.user_id} rule_id={self.rule_id} "
            f"missing {sides} issue id(s) {ids}"
        )

    def is_allowlisted(self) -> bool:
        """Return True when this row is the reviewed test-user exception."""
        return (self.rule_id, self.user_id) in DANGLING_RULE_ALLOWLIST


def _format_rule_ids(rule_ids: list[int]) -> str:
    """Return a compact, sorted id list for abort and skip messages."""
    shown = ", ".join(str(i) for i in sorted(rule_ids)[:_MAX_REPORTED_IDS])
    extra = (
        f" (and {len(rule_ids) - _MAX_REPORTED_IDS} more)"
        if len(rule_ids) > _MAX_REPORTED_IDS
        else ""
    )
    return f"{shown}{extra}"


def abort_with_rule_ids(rule_ids: list[int], reason: str) -> None:
    """Abort the migration with an actionable error listing the bad rules."""
    raise RuntimeError(
        f"Cannot backfill canonical Dependencies: {len(rule_ids)} rule(s) {reason}: "
        f"{_format_rule_ids(rule_ids)}. Resolve or remove these rules, then re-run "
        "the migration."
    )


def _query_rule_ids(bind: Connection, sql: str) -> list[int]:
    """Return integer rule ids from a single-column SELECT."""
    return [int(row[0]) for row in bind.execute(sa.text(sql)).all()]


def _load_item_read_dangling(bind: Connection) -> list[DanglingRuleReport]:
    """Return item_read native rules whose source or target issue is gone."""
    rows = bind.execute(
        sa.text(
            "SELECT r.id, r.user_id, r.source_id, r.target_id, "
            "s.id IS NULL AS missing_source, t.id IS NULL AS missing_target "
            "FROM continuity_rules r "
            "LEFT JOIN issues s ON s.id = r.source_id "
            "LEFT JOIN issues t ON t.id = r.target_id "
            f"WHERE r.{_NATIVE} AND r.satisfaction_type = 'item_read' "
            "AND (s.id IS NULL OR t.id IS NULL) "
            "ORDER BY r.id"
        )
    ).all()
    return [
        DanglingRuleReport(
            rule_id=int(row[0]),
            user_id=int(row[1]),
            source_id=int(row[2]),
            target_id=int(row[3]),
            missing_source=bool(row[4]),
            missing_target=bool(row[5]),
        )
        for row in rows
    ]


def abort_unknown_dangling_rules(unknown: list[DanglingRuleReport]) -> None:
    """Abort when dangling rules are not on the reviewed allowlist.

    Skipping an unreviewed dangling rule would silently drop a user's
    prerequisite from the compiled graph. That is never a warning.
    """
    if not unknown:
        return
    allowlist_ids = ", ".join(
        str(rule_id) for rule_id, _owner in sorted(DANGLING_RULE_ALLOWLIST)
    )
    details = "; ".join(row.report() for row in unknown[:_MAX_REPORTED_IDS])
    extra = (
        f" (and {len(unknown) - _MAX_REPORTED_IDS} more)"
        if len(unknown) > _MAX_REPORTED_IDS
        else ""
    )
    raise RuntimeError(
        "Cannot backfill canonical Dependencies: "
        f"{len(unknown)} dangling ContinuityRule(s) are not on the reviewed "
        f"allowlist of test-user {REVIEWED_DANGLING_OWNER_USER_ID} rule ids "
        f"({allowlist_ids}). Skipping them would silently weaken a user's "
        "prerequisites. Investigate: restore the missing issues, remove the "
        "rules, or explicitly expand the allowlist after review. "
        f"Offending rows: {details}{extra}."
    )


def _log_skipped_dangling(skipped: list[DanglingRuleReport]) -> None:
    """Log each reviewed dangling skip; the rows themselves are left unchanged."""
    for row in skipped:
        logger.warning(
            "Skipping reviewed dangling ContinuityRule "
            "(left unchanged, not compiled): %s",
            row.report(),
        )


def validate_compilable_rules(bind: Connection) -> list[DanglingRuleReport]:
    """Ensure compilable rule-native ContinuityRules reduce to issue-level edges.

    Dangling item_read rows on the reviewed allowlist are reported and left
    unchanged. Any other missing source, target, or prerequisite aborts with
    an investigation-grade error. Cycles, non-issue endpoints, cross-user
    references, and unhandled types still abort.

    Args:
        bind: Synchronous SQLAlchemy connection used by Alembic.

    Returns:
        Allowlisted dangling rows that were skipped (never mutated).
    """
    native = _NATIVE

    bad_types = _query_rule_ids(
        bind,
        "SELECT id FROM continuity_rules "
        f"WHERE {native} AND satisfaction_type NOT IN ('item_read', 'converged')",
    )
    if bad_types:
        abort_with_rule_ids(bad_types, "have unhandled satisfaction_type values")

    non_issue = _query_rule_ids(
        bind,
        "SELECT id FROM continuity_rules "
        f"WHERE {native} AND satisfaction_type = 'item_read' "
        "AND (source_type <> 'issue' OR target_type <> 'issue')",
    )
    if non_issue:
        abort_with_rule_ids(non_issue, "are item_read rules with non-issue endpoints")

    dangling_item_read = _load_item_read_dangling(bind)
    allowlisted = [row for row in dangling_item_read if row.is_allowlisted()]
    abort_unknown_dangling_rules(
        [row for row in dangling_item_read if not row.is_allowlisted()]
    )

    cross_user = _query_rule_ids(
        bind,
        "SELECT r.id FROM continuity_rules r "
        "JOIN issues s ON s.id = r.source_id "
        "JOIN issues t ON t.id = r.target_id "
        "JOIN threads st ON st.id = s.thread_id "
        "JOIN threads tt ON tt.id = t.thread_id "
        f"WHERE r.{native} AND r.satisfaction_type = 'item_read' "
        "AND (st.user_id <> r.user_id OR tt.user_id <> r.user_id)",
    )
    if cross_user:
        abort_with_rule_ids(cross_user, "reference issues owned by a different user than the rule")

    bad_converged_target = _query_rule_ids(
        bind,
        "SELECT r.id FROM continuity_rules r "
        "LEFT JOIN issues t ON t.id = r.target_id "
        "LEFT JOIN threads tt ON tt.id = t.thread_id "
        f"WHERE r.{native} AND r.satisfaction_type = 'converged' "
        "AND (r.target_type <> 'issue' OR t.id IS NULL OR tt.user_id <> r.user_id)",
    )
    if bad_converged_target:
        abort_with_rule_ids(
            bad_converged_target,
            "are converged rules with a non-issue, missing, or cross-user target",
        )

    bad_prereq = _query_rule_ids(
        bind,
        # NB: the issues join compares on text so a malformed id is
        # reported by this validation instead of raising a cast error.
        "SELECT DISTINCT r.id FROM continuity_rules r, "
        "LATERAL json_array_elements(r.convergence_targets) AS elem "
        "LEFT JOIN issues i ON i.id::text = elem->>'id' "
        "LEFT JOIN threads th ON th.id = i.thread_id "
        f"WHERE r.{native} AND r.satisfaction_type = 'converged' "
        "AND (elem->>'id' !~ '^[0-9]+$' OR elem->>'type' <> 'issue' "
        "OR i.id IS NULL OR th.user_id <> r.user_id)",
    )
    if bad_prereq:
        abort_with_rule_ids(
            bad_prereq,
            "have convergence prerequisites that are not existing issues "
            "owned by the rule's user",
        )

    _log_skipped_dangling(allowlisted)
    _abort_on_cycles(bind)
    return allowlisted


def abort_on_retired_list_chain_rules(bind: Connection) -> None:
    """Abort the cutover if a rule-native item_read rule is a retired list chain.

    Per ``docs/roll-eligibility-contract.md`` (Josh, 2026-10-12), a hard
    Dependency whose source and target are consecutive ``Issue.position``
    entries of the same ``Thread`` is generated series-order adjacency, not
    an authoritative blocker: natural series order is owned by
    ``Thread.next_unread_issue_id``. Such rows were produced by the retired
    whole-list chain compiles; re-running this legacy migration must not
    resurrect them, so their presence aborts with an investigation-grade
    error listing the rule ids to retire first.

    Args:
        bind: Synchronous SQLAlchemy connection used by Alembic.

    Raises:
        RuntimeError: When any rule-native item_read rule duplicates natural
            series adjacency.
    """
    chain_rules = _query_rule_ids(
        bind,
        "SELECT r.id FROM continuity_rules r "
        "JOIN issues s ON s.id = r.source_id "
        "JOIN issues t ON t.id = r.target_id "
        f"WHERE r.{_NATIVE} AND r.satisfaction_type = 'item_read' "
        "AND r.source_type = 'issue' AND r.target_type = 'issue' "
        "AND s.thread_id = t.thread_id "
        "AND t.position = s.position + 1",
    )
    if chain_rules:
        abort_with_rule_ids(
            chain_rules,
            "are retired generated list-chain rules duplicating natural "
            "series order (same thread, consecutive Issue.position); retire "
            "them per docs/roll-eligibility-contract.md before re-running "
            "the cutover",
        )


def drop_mirror_trigger(bind: Connection) -> None:
    """Remove the Dependency -> ContinuityRule compatibility bridge."""
    bind.execute(sa.text("DROP TRIGGER IF EXISTS trg_sync_legacy_dependency_to_continuity_rule ON dependencies"))
    bind.execute(sa.text("DROP FUNCTION IF EXISTS sync_legacy_dependency_to_continuity_rule()"))


def _abort_on_cbl_collisions(bind: Connection, pairs_sql: str) -> None:
    """Abort if a historical cbl-order row occupies a pair a rule must compile.

    ON CONFLICT DO NOTHING would silently treat the inert historical row as
    success, leaving the hard rule without a blocking edge. The September
    audit measured zero collisions; any collision is a data problem to fix,
    not to paper over.

    pairs_sql filters continuity_rules r to the rules being compiled; the
    pair join uses r.source_id/r.target_id (item_read shape).
    """
    collisions = [
        row[0]
        for row in bind.execute(
            sa.text(
                "SELECT DISTINCT r.id FROM continuity_rules r "
                "JOIN dependencies d ON "
                "d.source_issue_id = r.source_id AND d.target_issue_id = r.target_id "
                f"WHERE {pairs_sql} AND d.note LIKE 'cbl-order:%'"
            )
        ).all()
    ]
    if collisions:
        abort_with_rule_ids(
            collisions,
            "collide with historical cbl-order rows that would stay inert; "
            "resolve the overlap before running the cutover",
        )


def _abort_on_converged_cbl_collisions(bind: Connection) -> None:
    """Abort if a historical cbl-order row occupies a converged prerequisite pair."""
    collisions = [
        row[0]
        for row in bind.execute(
            sa.text(
                "SELECT DISTINCT r.id FROM continuity_rules r "
                "JOIN LATERAL json_array_elements(r.convergence_targets) AS elem ON true "
                "JOIN dependencies d ON "
                "d.source_issue_id = (elem->>'id')::int "
                "AND d.target_issue_id = r.target_id "
                "WHERE r.legacy_dependency_id IS NULL "
                "AND r.satisfaction_type = 'converged' "
                "AND (elem->>'id')::int <> r.target_id "
                "AND d.note LIKE 'cbl-order:%'"
            )
        ).all()
    ]
    if collisions:
        abort_with_rule_ids(
            collisions,
            "collide with historical cbl-order rows that would stay inert; "
            "resolve the overlap before running the cutover",
        )


def _rule_native_pairs(bind: Connection) -> list[tuple[int, int, int]]:
    """Return (rule_id, source_issue_id, target_issue_id) the backfill would persist.

    Dangling rules (missing source, target, or converged prerequisite issues)
    are omitted so they cannot participate in cycle detection or compilation.
    """
    item_read = bind.execute(
        sa.text(
            "SELECT r.id, r.source_id, r.target_id FROM continuity_rules r "
            "WHERE r.legacy_dependency_id IS NULL "
            "AND r.satisfaction_type = 'item_read' "
            "AND r.source_type = 'issue' AND r.target_type = 'issue' "
            "AND r.source_id <> r.target_id "
            f"AND {_ITEM_READ_ENDPOINTS_EXIST}"
        )
    ).all()
    converged = bind.execute(
        sa.text(
            "SELECT r.id, (elem->>'id')::int, r.target_id "
            "FROM continuity_rules r "
            "JOIN LATERAL json_array_elements(r.convergence_targets) AS elem "
            "ON elem->>'id' ~ '^[0-9]+$' "
            "JOIN issues prereq ON prereq.id = (elem->>'id')::int "
            "JOIN issues target ON target.id = r.target_id "
            "WHERE r.legacy_dependency_id IS NULL "
            "AND r.satisfaction_type = 'converged' "
            "AND (elem->>'id')::int <> r.target_id"
        )
    ).all()
    return [(int(row[0]), int(row[1]), int(row[2])) for row in (*item_read, *converged)]


def _abort_on_cycles(bind: Connection) -> None:
    """Abort if rule-native pairs plus existing canonical edges form a cycle.

    A cycle would block the involved threads forever with no migration error.
    Historical ``cbl-order:%`` rows are ignored here, matching the evaluator.
    """
    existing = bind.execute(
        sa.text(
            "SELECT source_issue_id, target_issue_id FROM dependencies "
            "WHERE note IS NULL OR note NOT LIKE 'cbl-order:%'"
        )
    ).all()
    rule_pairs = _rule_native_pairs(bind)
    adjacency: dict[int, set[int]] = defaultdict(set)
    incoming: dict[int, int] = defaultdict(int)
    nodes: set[int] = set()
    for source_id, target_id in existing:
        src, tgt = int(source_id), int(target_id)
        if tgt in adjacency[src]:
            continue
        adjacency[src].add(tgt)
        incoming[tgt] += 1
        nodes.add(src)
        nodes.add(tgt)
    for _rule_id, source_id, target_id in rule_pairs:
        if target_id in adjacency[source_id]:
            continue
        adjacency[source_id].add(target_id)
        incoming[target_id] += 1
        nodes.add(source_id)
        nodes.add(target_id)
    if not nodes:
        return
    remaining_incoming = {node: incoming.get(node, 0) for node in nodes}
    queue: deque[int] = deque(node for node, count in remaining_incoming.items() if count == 0)
    while queue:
        node = queue.popleft()
        for nxt in adjacency[node]:
            remaining_incoming[nxt] -= 1
            if remaining_incoming[nxt] == 0:
                queue.append(nxt)
    cyclic_nodes = {node for node, count in remaining_incoming.items() if count > 0}
    if not cyclic_nodes:
        return
    cyclic_rule_ids = sorted(
        {
            rule_id
            for rule_id, source_id, target_id in rule_pairs
            if source_id in cyclic_nodes and target_id in cyclic_nodes
            and target_id in adjacency[source_id]
        }
    )
    if cyclic_rule_ids:
        abort_with_rule_ids(
            cyclic_rule_ids,
            "would form a dependency cycle with existing canonical edges",
        )


def revert_backfilled_edges(bind: Connection) -> int:
    """Delete only Dependency rows inserted by this cutover backfill.

    Live write-path edges use ``canonical:rule:<id>`` and must survive
    downgrade; their ``reading_plan_dependencies`` links stay with them.
    Backfill notes are ``canonical:rule-backfill:<id>``. CASCADE unlinks
    only the provenance rows for the deleted backfill edges.
    """
    result = bind.execute(
        sa.text("DELETE FROM dependencies WHERE note LIKE :pattern"),
        {"pattern": f"{BACKFILL_EDGE_NOTE_PREFIX}%"},
    )
    return int(result.rowcount or 0)


def backfill_item_read_edges(bind: Connection) -> tuple[int, int]:
    """Persist one edge per rule-native item_read rule. Returns (inserted, skipped_existing)."""
    _abort_on_cbl_collisions(
        bind,
        "r.legacy_dependency_id IS NULL AND r.satisfaction_type = 'item_read'",
    )
    before = bind.execute(sa.text("SELECT COUNT(*) FROM dependencies")).scalar_one()
    bind.execute(
        sa.text(
            "INSERT INTO dependencies (source_issue_id, target_issue_id, note, created_at) "
            "SELECT r.source_id, r.target_id, "
            f"'{BACKFILL_EDGE_NOTE_PREFIX}' || r.id, now() "
            "FROM continuity_rules r "
            "WHERE r.legacy_dependency_id IS NULL "
            "AND r.satisfaction_type = 'item_read' "
            "AND r.source_type = 'issue' AND r.target_type = 'issue' "
            f"AND {_ITEM_READ_ENDPOINTS_EXIST} "
            "ON CONFLICT (source_issue_id, target_issue_id) DO NOTHING"
        )
    )
    after = bind.execute(sa.text("SELECT COUNT(*) FROM dependencies")).scalar_one()
    distinct_pairs = bind.execute(
        sa.text(
            "SELECT COUNT(DISTINCT (r.source_id, r.target_id)) FROM continuity_rules r "
            "WHERE r.legacy_dependency_id IS NULL AND r.satisfaction_type = 'item_read' "
            "AND r.source_type = 'issue' AND r.target_type = 'issue' "
            f"AND {_ITEM_READ_ENDPOINTS_EXIST}"
        )
    ).scalar_one()
    inserted = after - before
    return inserted, distinct_pairs - inserted


def backfill_converged_edges(bind: Connection) -> tuple[int, int, int]:
    """Expand converged rules into per-prerequisite edges. Returns (inserted, skipped_existing, skipped_self)."""
    _abort_on_converged_cbl_collisions(bind)
    self_edges = bind.execute(
        sa.text(
            "SELECT COUNT(DISTINCT (elem->>'id')::int) FROM continuity_rules r "
            "JOIN LATERAL json_array_elements(r.convergence_targets) AS elem "
            "ON elem->>'id' ~ '^[0-9]+$' "
            "JOIN issues prereq ON prereq.id = (elem->>'id')::int "
            "JOIN issues target ON target.id = r.target_id "
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
            f"'{BACKFILL_EDGE_NOTE_PREFIX}' || r.id, now() "
            "FROM continuity_rules r "
            "JOIN LATERAL json_array_elements(r.convergence_targets) AS elem "
            "ON elem->>'id' ~ '^[0-9]+$' "
            "JOIN issues prereq ON prereq.id = (elem->>'id')::int "
            "JOIN issues target ON target.id = r.target_id "
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
            "FROM continuity_rules r "
            "JOIN LATERAL json_array_elements(r.convergence_targets) AS elem "
            "ON elem->>'id' ~ '^[0-9]+$' "
            "JOIN issues prereq ON prereq.id = (elem->>'id')::int "
            "JOIN issues target ON target.id = r.target_id "
            "WHERE r.legacy_dependency_id IS NULL "
            "AND r.satisfaction_type = 'converged' "
            "AND (elem->>'id')::int <> r.target_id"
        )
    ).scalar_one()
    inserted = after - before
    return inserted, prereq_count - inserted, self_edges


def _issue_exists(bind: Connection, issue_id: int) -> bool:
    """Return True when ``issue_id`` exists in the issues table."""
    found = bind.execute(
        sa.text("SELECT 1 FROM issues WHERE id = :issue_id"),
        {"issue_id": issue_id},
    ).first()
    return found is not None


def _issues_exist(bind: Connection, issue_ids: list[int]) -> bool:
    """Return True when every id exists in the issues table."""
    return all(_issue_exists(bind, issue_id) for issue_id in dict.fromkeys(issue_ids))


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
    Allowlisted dangling item_read rows are skip-and-reported with owner,
    rule id, missing issue ids, and missing side. Any other missing
    endpoint — especially a user-owned prerequisite — aborts.
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
        endpoint_ids = [issue_id for pair in pairs for issue_id in pair]
        if satisfaction_type == "item_read":
            report = DanglingRuleReport(
                rule_id=int(rule_id),
                user_id=int(user_id),
                source_id=int(source_id),
                target_id=int(target_id),
                missing_source=not _issue_exists(bind, int(source_id)),
                missing_target=not _issue_exists(bind, int(target_id)),
            )
            if report.missing_source or report.missing_target:
                if report.is_allowlisted():
                    skipped.append((int(rule_id), report.report()))
                    continue
                abort_unknown_dangling_rules([report])
        elif not _issues_exist(bind, endpoint_ids):
            missing = [
                issue_id
                for issue_id in dict.fromkeys(endpoint_ids)
                if not _issue_exists(bind, issue_id)
            ]
            abort_with_rule_ids(
                [int(rule_id)],
                "have a missing target or prerequisite issue "
                f"(user_id={int(user_id)}, missing issue id(s) "
                f"{', '.join(str(issue_id) for issue_id in missing)}); "
                "skipping would silently weaken a user's prerequisites",
            )
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



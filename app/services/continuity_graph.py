"""Shared continuity graph snapshot and per-node readiness primitives.

Public home for graph-snapshot loading and per-node readiness helpers used by
continuity readiness, plan readiness, blocking, and chain traversal. Centralizing
these primitives behind a documented public API lets the base readiness module
refactor freely without silently breaking plan-readiness consumers.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_rule import ContinuityRule, ContinuityRuleSelectedMember
from app.models.dependency_group import DependencyGroup, DependencyGroupMembership
from app.models.issue import Issue
from app.models.thread import Thread
from app.schemas.continuity_readiness import (
    ContinuityBlocker,
    UnreadIssueDetail,
)

logger = logging.getLogger(__name__)

MAX_GRAPH_THREADS = 5_000
MAX_GRAPH_ISSUES = 10_000
MAX_GRAPH_GROUPS = 5_000
MAX_GRAPH_MEMBERSHIPS = 10_000
MAX_GRAPH_RULES = 5_000
MAX_GRAPH_SELECTED_MEMBERS = 10_000

SNAPSHOT_SESSION_KEY = "continuity_readiness_snapshot"


@dataclass(frozen=True)
class GraphSnapshot:
    """User-owned continuity data loaded in a bounded set of queries.

    Attributes:
        threads: Threads owned by the user keyed by thread id.
        issues: Issues owned by the user keyed by issue id.
        groups: Dependency groups (crossovers) owned by the user keyed by id.
        group_memberships: Membership rows grouped by crossover id.
        rules: All continuity rules owned by the user.
        rules_by_target: Rules grouped by ``(target_type, target_id)``.
        thread_issue_ids: Issue ids per thread.
        selected_member_issue_ids: Selected member issue ids per rule.
        query_count: Number of bounded queries used to build the snapshot.
        rows_loaded: Total rows materialized across the bounded queries.
    """

    threads: dict[int, Thread]
    issues: dict[int, Issue]
    groups: dict[int, DependencyGroup]
    group_memberships: dict[int, tuple[DependencyGroupMembership, ...]]
    rules: tuple[ContinuityRule, ...]
    rules_by_target: dict[tuple[str, int], tuple[ContinuityRule, ...]]
    thread_issue_ids: dict[int, tuple[int, ...]]
    selected_member_issue_ids: dict[int, tuple[int, ...]]
    crossover_ordered_issue_ids: dict[int, tuple[int, ...]]
    issue_crossover_positions: dict[int, tuple[tuple[int, int], ...]]
    query_count: int = 0
    rows_loaded: int = 0


def _too_large(limit: int) -> HTTPException:
    """Build the shared bounded-graph response for one exceeded collection."""
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": "continuity_graph_too_large", "limit": limit},
    )


def _validate_convergence_rule(rule: ContinuityRule, snapshot: GraphSnapshot) -> None:
    """Validate convergence gate configuration for validity.

    Args:
        rule: The convergence rule being evaluated.
        snapshot: The loaded continuity graph snapshot.

    Raises:
        ValueError: If the convergence targets are malformed or reference unknown nodes.
    """
    if rule.satisfaction_type != "converged" or rule.convergence_targets is None:
        return
    seen: set[tuple[str, int]] = set()
    for target_info in rule.convergence_targets:
        if not isinstance(target_info, dict) or "type" not in target_info or "id" not in target_info:
            raise ValueError(
                f"Convergence targets must be objects with 'type' and 'id' (rule {rule.id})"
            )
        target_type = str(target_info["type"])
        target_id = int(target_info["id"])
        if (target_type, target_id) in seen:
            raise ValueError(f"Convergence gate references a duplicate target (rule {rule.id})")
        seen.add((target_type, target_id))
        if target_type == "issue":
            if target_id not in snapshot.issues:
                raise ValueError(f"Convergence target issue {target_id} is unknown (rule {rule.id})")
        elif target_type == "crossover":
            if target_id not in snapshot.groups:
                raise ValueError(
                    f"Convergence target crossover {target_id} is unknown (rule {rule.id})"
                )
        else:
            raise ValueError(f"Unknown convergence target type '{target_type}' (rule {rule.id})")


def _group_rows[T](rows: list[T], key: Callable[[T], int]) -> dict[int, tuple[T, ...]]:
    """Group bounded child rows by their parent identifier."""
    grouped: dict[int, list[T]] = {}
    for row in rows:
        grouped.setdefault(key(row), []).append(row)
    return {parent_id: tuple(children) for parent_id, children in grouped.items()}


async def load_snapshot(db: AsyncSession, user_id: int) -> GraphSnapshot:
    """Load the authenticated user's direct-readiness graph without per-row queries.

    The snapshot is cached on the session (``db.info``) so that multiple
    continuity calculations within the same request reuse the same bounded
    load rather than repeating the full query sequence.

    Args:
        db: Database session used to load the authenticated user's graph.
        user_id: Authenticated user whose owned graph should be evaluated.

    Returns:
        Snapshot with ``query_count`` and ``rows_loaded`` tracking the number
        of round-trips and total rows materialized for observability.
    """
    if db.info is None:
        db.info = {}
    session_cache = db.info.setdefault(SNAPSHOT_SESSION_KEY, {})
    cached = session_cache.get(user_id)
    if cached is not None:
        logger.debug(
            "Continuity snapshot cache hit",
            extra={"user_id": user_id, "query_count": cached.query_count, "rows_loaded": cached.rows_loaded},
        )
        return cached

    query_count = 0
    rows_loaded = 0

    thread_result = await db.execute(
        select(Thread)
        .where(Thread.user_id == user_id)
        .order_by(Thread.id)
        .limit(MAX_GRAPH_THREADS + 1)
    )
    query_count += 1
    thread_rows = list(thread_result.scalars())
    rows_loaded += len(thread_rows)
    if len(thread_rows) > MAX_GRAPH_THREADS:
        raise _too_large(MAX_GRAPH_THREADS)
    threads = {thread.id: thread for thread in thread_rows}

    issue_result = await db.execute(
        select(Issue)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Thread.user_id == user_id)
        .order_by(Issue.id)
        .limit(MAX_GRAPH_ISSUES + 1)
    )
    query_count += 1
    issue_rows = list(issue_result.scalars())
    rows_loaded += len(issue_rows)
    if len(issue_rows) > MAX_GRAPH_ISSUES:
        raise _too_large(MAX_GRAPH_ISSUES)
    issues = {issue.id: issue for issue in issue_rows}
    thread_issue_ids = {
        thread_id: tuple(issue.id for issue in thread_issues)
        for thread_id, thread_issues in _group_rows(issue_rows, lambda issue: issue.thread_id).items()
    }

    group_result = await db.execute(
        select(DependencyGroup)
        .where(DependencyGroup.user_id == user_id)
        .order_by(DependencyGroup.id)
        .limit(MAX_GRAPH_GROUPS + 1)
    )
    query_count += 1
    group_rows = list(group_result.scalars())
    rows_loaded += len(group_rows)
    if len(group_rows) > MAX_GRAPH_GROUPS:
        raise _too_large(MAX_GRAPH_GROUPS)
    groups = {group.id: group for group in group_rows}

    membership_result = await db.execute(
        select(DependencyGroupMembership)
        .join(DependencyGroup, DependencyGroup.id == DependencyGroupMembership.group_id)
        .where(DependencyGroup.user_id == user_id)
        .order_by(DependencyGroupMembership.id)
        .limit(MAX_GRAPH_MEMBERSHIPS + 1)
    )
    query_count += 1
    membership_rows = list(membership_result.scalars())
    rows_loaded += len(membership_rows)
    if len(membership_rows) > MAX_GRAPH_MEMBERSHIPS:
        raise _too_large(MAX_GRAPH_MEMBERSHIPS)
    group_memberships = _group_rows(membership_rows, lambda membership: membership.group_id)

    rule_result = await db.execute(
        select(ContinuityRule)
        .where(ContinuityRule.user_id == user_id)
        .order_by(ContinuityRule.id)
        .limit(MAX_GRAPH_RULES + 1)
    )
    query_count += 1
    rule_rows = list(rule_result.scalars())
    rows_loaded += len(rule_rows)
    if len(rule_rows) > MAX_GRAPH_RULES:
        raise _too_large(MAX_GRAPH_RULES)
    rules = tuple(rule_rows)
    grouped_rules: dict[tuple[str, int], list[ContinuityRule]] = {}
    for rule in rule_rows:
        grouped_rules.setdefault((rule.target_type, rule.target_id), []).append(rule)
    rules_by_target = {
        target: tuple(target_rules) for target, target_rules in grouped_rules.items()
    }

    selected_member_result = await db.execute(
        select(ContinuityRuleSelectedMember)
        .join(ContinuityRule, ContinuityRule.id == ContinuityRuleSelectedMember.rule_id)
        .where(ContinuityRule.user_id == user_id)
        .order_by(ContinuityRuleSelectedMember.id)
        .limit(MAX_GRAPH_SELECTED_MEMBERS + 1)
    )
    query_count += 1
    selected_member_rows = list(selected_member_result.scalars())
    rows_loaded += len(selected_member_rows)
    if len(selected_member_rows) > MAX_GRAPH_SELECTED_MEMBERS:
        raise _too_large(MAX_GRAPH_SELECTED_MEMBERS)
    selected_member_issue_ids = {
        rule_id: tuple(member.issue_id for member in members)
        for rule_id, members in _group_rows(
            selected_member_rows, lambda member: member.rule_id
        ).items()
    }

    crossover_ordered_issue_ids = {
        group_id: tuple(
            membership.issue_id
            for membership in sorted(
                (
                    row
                    for row in rows
                    if row.issue_id is not None and row.sequence_order is not None
                ),
                key=lambda membership: (membership.sequence_order, membership.id),
            )
        )
        for group_id, rows in group_memberships.items()
    }
    issue_crossover_positions: dict[int, list[tuple[int, int]]] = {}
    for group_id, ordered_ids in crossover_ordered_issue_ids.items():
        for position, issue_id in enumerate(ordered_ids, start=1):
            issue_crossover_positions.setdefault(issue_id, []).append((group_id, position))
    normalized_positions = {
        issue_id: tuple(sorted(groups))
        for issue_id, groups in issue_crossover_positions.items()
    }

    snapshot = GraphSnapshot(
        threads=threads,
        issues=issues,
        groups=groups,
        group_memberships=group_memberships,
        rules=rules,
        rules_by_target=rules_by_target,
        thread_issue_ids=thread_issue_ids,
        selected_member_issue_ids=selected_member_issue_ids,
        crossover_ordered_issue_ids=crossover_ordered_issue_ids,
        issue_crossover_positions=normalized_positions,
        query_count=query_count,
        rows_loaded=rows_loaded,
    )
    if db.info is None:
        db.info = {}
    session_cache = db.info.setdefault(SNAPSHOT_SESSION_KEY, {})
    session_cache[user_id] = snapshot
    logger.debug(
        "Continuity snapshot loaded and cached",
        extra={"user_id": user_id, "query_count": query_count, "rows_loaded": rows_loaded},
    )
    return snapshot


def group_issue_ids(group_id: int, snapshot: GraphSnapshot) -> list[int]:
    """Return all issue IDs represented by a crossover, including thread memberships.

    Args:
        group_id: Crossover group identifier.
        snapshot: Loaded continuity graph snapshot.

    Returns:
        Sorted issue ids that belong to the crossover either directly or via
        thread membership.
    """
    memberships = snapshot.group_memberships.get(group_id, ())
    issue_ids = {membership.issue_id for membership in memberships if membership.issue_id}
    thread_ids = {membership.thread_id for membership in memberships if membership.thread_id}
    for thread_id in thread_ids:
        issue_ids.update(snapshot.thread_issue_ids.get(thread_id, ()))
    return sorted(issue_ids)


def _source_label(rule: ContinuityRule, snapshot: GraphSnapshot) -> str:
    """Return a stable human label while keeping blocker identity structured."""
    if rule.source_type == "crossover":
        group = snapshot.groups.get(rule.source_id)
        return group.name if group is not None else f"Crossover {rule.source_id}"
    issue = snapshot.issues.get(rule.source_id)
    if issue is None:
        return f"Issue {rule.source_id}"
    thread = snapshot.threads.get(issue.thread_id)
    if thread is None:
        return f"Issue {issue.issue_number}"
    return f"{thread.title} #{issue.issue_number}"


def _issue_detail(issue_id: int, snapshot: GraphSnapshot) -> UnreadIssueDetail:
    """Build a structured label for one unread issue."""
    issue = snapshot.issues.get(issue_id)
    if issue is None:
        return UnreadIssueDetail(issue_id=issue_id, label=f"Issue {issue_id}")
    thread = snapshot.threads.get(issue.thread_id)
    label = f"#{issue.issue_number}" if thread is None else f"{thread.title} #{issue.issue_number}"
    return UnreadIssueDetail(issue_id=issue_id, label=label)


def is_read(issue_id: int, snapshot: GraphSnapshot) -> bool:
    """Return whether one owned issue is read.

    Args:
        issue_id: Issue identifier.
        snapshot: Loaded continuity graph snapshot.

    Returns:
        True when the issue exists and its status is ``read``.
    """
    issue = snapshot.issues.get(issue_id)
    return issue is not None and issue.status == "read"


def _evaluate_rule(rule: ContinuityRule, snapshot: GraphSnapshot) -> ContinuityBlocker | None:
    """Return a blocker when one direct rule's satisfaction policy is not met."""
    causing_issue_ids: list[int] = []
    causing_member_issue_ids: list[int] = []

    if rule.satisfaction_type == "item_read":
        if rule.source_type == "issue":
            causing_issue_ids = [] if is_read(rule.source_id, snapshot) else [rule.source_id]
        else:
            member_ids = group_issue_ids(rule.source_id, snapshot)
            causing_member_issue_ids = [
                issue_id for issue_id in member_ids if not is_read(issue_id, snapshot)
            ]
    elif rule.satisfaction_type == "all_members_read":
        if rule.source_type == "crossover":
            member_ids = group_issue_ids(rule.source_id, snapshot)
            causing_member_issue_ids = [
                issue_id for issue_id in member_ids if not is_read(issue_id, snapshot)
            ]
        else:
            causing_issue_ids = [] if is_read(rule.source_id, snapshot) else [rule.source_id]
    elif rule.satisfaction_type == "checkpoint":
        checkpoint_id = rule.checkpoint_issue_id
        if checkpoint_id is not None and not is_read(checkpoint_id, snapshot):
            causing_issue_ids = [checkpoint_id]
    elif rule.satisfaction_type == "converged":
        _validate_convergence_rule(rule, snapshot)
        for target_info in rule.convergence_targets or []:
            target_type = str(target_info["type"])
            target_id = int(target_info["id"])
            if target_type == "issue":
                if not is_read(target_id, snapshot):
                    causing_issue_ids.append(target_id)
            elif target_type == "crossover":
                member_ids = group_issue_ids(target_id, snapshot)
                causing_member_issue_ids.extend(
                    issue_id for issue_id in member_ids if not is_read(issue_id, snapshot)
                )
    else:
        selected_ids = snapshot.selected_member_issue_ids.get(rule.id, ())
        causing_member_issue_ids = [
            issue_id for issue_id in selected_ids if not is_read(issue_id, snapshot)
        ]

    if not causing_issue_ids and not causing_member_issue_ids:
        return None
    if causing_member_issue_ids:
        if rule.satisfaction_type not in {"item_read", "all_members_read"}:
            blocker_type = "selected_members_unread"
        else:
            blocker_type = "members_unread"
    else:
        blocker_type = "item_unread"
    all_unread_ids = sorted(set(causing_issue_ids + causing_member_issue_ids))
    return ContinuityBlocker(
        rule_id=rule.id,
        source_type=rule.source_type,
        source_id=rule.source_id,
        source_label=_source_label(rule, snapshot),
        satisfaction_type=rule.satisfaction_type,
        blocker_type=blocker_type,
        causing_issue_ids=causing_issue_ids,
        causing_member_issue_ids=causing_member_issue_ids,
        unread_issue_details=[_issue_detail(uid, snapshot) for uid in all_unread_ids],
        note=rule.note,
    )


def _direct_blockers(
    node_type: str,
    node_id: int,
    snapshot: GraphSnapshot,
) -> list[ContinuityBlocker]:
    """Evaluate rules directly targeting one issue or crossover node."""
    blockers: list[ContinuityBlocker] = []
    for rule in snapshot.rules_by_target.get((node_type, node_id), ()):
        blocker = _evaluate_rule(rule, snapshot)
        if blocker is not None:
            blockers.append(blocker)
    return blockers


def crossover_order_blockers(issue_id: int, snapshot: GraphSnapshot) -> list[ContinuityBlocker]:
    """Return crossover ordering blockers for one issue, AND-composed across crossovers.

    For every active crossover that contains the issue as an ordered entry, the
    issue is blocked while any earlier unread ordered entry remains. An issue
    belonging to multiple ordered crossovers must satisfy every one of them, so
    any unsatisfied earlier prerequisite produces a blocker.

    Args:
        issue_id: The owned issue to evaluate against crossover reading order.
        snapshot: Loaded continuity graph snapshot.

    Returns:
        One ``crossover_order`` blocker per active ordered crossover with an
        earlier unread entry, each naming the crossover and the earliest earlier
        unread issue.
    """
    if snapshot.issues.get(issue_id) is None:
        return []
    target_label = _issue_detail(issue_id, snapshot).label
    markers: list[ContinuityBlocker] = []
    for group_id, position in snapshot.issue_crossover_positions.get(issue_id, ()):
        ordered_ids = snapshot.crossover_ordered_issue_ids.get(group_id, ())
        if position <= 1:
            continue
        for earlier_id in ordered_ids[: position - 1]:
            if is_read(earlier_id, snapshot):
                continue
            group = snapshot.groups[group_id]
            earlier_label = _issue_detail(earlier_id, snapshot).label
            markers.append(
                ContinuityBlocker(
                    rule_id=None,
                    source_type="crossover",
                    source_id=group_id,
                    source_label=group.name,
                    satisfaction_type="all_members_read",
                    blocker_type="crossover_order",
                    causing_member_issue_ids=[earlier_id],
                    unread_issue_details=[UnreadIssueDetail(issue_id=earlier_id, label=earlier_label)],
                    note=(
                        f"Read {earlier_label} before {target_label} in {group.name}."
                    ),
                    crossover_id=group_id,
                    sequence_position=position,
                )
            )
            break
    return markers


def issue_readiness(issue_id: int, snapshot: GraphSnapshot) -> list[ContinuityBlocker]:
    """Return direct blockers for one issue, including crossover ordering.

    Args:
        issue_id: Issue identifier.
        snapshot: Loaded continuity graph snapshot.

    Returns:
        Direct continuity-rule blockers plus any crossover ordering blockers that
        prevent the issue from being read before earlier ordered entries.
    """
    return _direct_blockers("issue", issue_id, snapshot) + crossover_order_blockers(
        issue_id, snapshot
    )


def crossover_readiness(group_id: int, snapshot: GraphSnapshot) -> list[ContinuityBlocker]:
    """Return direct crossover blockers plus blockers on unread member issues.

    Args:
        group_id: Crossover group identifier.
        snapshot: Loaded continuity graph snapshot.

    Returns:
        Direct blockers targeting the crossover and any blockers that apply to
        its unread member issues, sorted by rule id.
    """
    blockers = _direct_blockers("crossover", group_id, snapshot)
    seen = {
        (blocker.rule_id, blocker.source_type, blocker.source_id)
        for blocker in blockers
    }
    for issue_id in group_issue_ids(group_id, snapshot):
        if is_read(issue_id, snapshot):
            continue
        for blocker in issue_readiness(issue_id, snapshot):
            key = (blocker.rule_id, blocker.source_type, blocker.source_id)
            if key not in seen:
                blockers.append(blocker)
                seen.add(key)
    blockers.sort(key=lambda blocker: blocker.rule_id if blocker.rule_id is not None else -1)
    return blockers

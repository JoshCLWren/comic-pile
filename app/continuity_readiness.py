"""Bounded direct readiness evaluation for generalized continuity rules."""

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
    ContinuityReadinessNodeType,
    ContinuityReadinessResponse,
)

MAX_GRAPH_THREADS = 5_000
MAX_GRAPH_ISSUES = 10_000
MAX_GRAPH_GROUPS = 5_000
MAX_GRAPH_MEMBERSHIPS = 10_000
MAX_GRAPH_RULES = 5_000
MAX_GRAPH_SELECTED_MEMBERS = 10_000


@dataclass(frozen=True)
class _GraphSnapshot:
    """User-owned continuity data loaded in a bounded set of queries."""

    threads: dict[int, Thread]
    issues: dict[int, Issue]
    groups: dict[int, DependencyGroup]
    group_memberships: dict[int, tuple[DependencyGroupMembership, ...]]
    rules: tuple[ContinuityRule, ...]
    rules_by_target: dict[tuple[str, int], tuple[ContinuityRule, ...]]
    thread_issue_ids: dict[int, tuple[int, ...]]
    selected_member_issue_ids: dict[int, tuple[int, ...]]


def _too_large(limit: int) -> HTTPException:
    """Build the shared bounded-graph response for one exceeded collection."""
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": "continuity_graph_too_large", "limit": limit},
    )


def _group_rows[T](rows: list[T], key: Callable[[T], int]) -> dict[int, tuple[T, ...]]:
    """Group bounded child rows by their parent identifier."""
    grouped: dict[int, list[T]] = {}
    for row in rows:
        grouped.setdefault(key(row), []).append(row)
    return {parent_id: tuple(children) for parent_id, children in grouped.items()}


async def _load_snapshot(db: AsyncSession, user_id: int) -> _GraphSnapshot:
    """Load the authenticated user's direct-readiness graph without per-row queries."""
    thread_result = await db.execute(
        select(Thread)
        .where(Thread.user_id == user_id)
        .order_by(Thread.id)
        .limit(MAX_GRAPH_THREADS + 1)
    )
    thread_rows = list(thread_result.scalars())
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
    issue_rows = list(issue_result.scalars())
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
    group_rows = list(group_result.scalars())
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
    membership_rows = list(membership_result.scalars())
    if len(membership_rows) > MAX_GRAPH_MEMBERSHIPS:
        raise _too_large(MAX_GRAPH_MEMBERSHIPS)
    group_memberships = _group_rows(membership_rows, lambda membership: membership.group_id)

    rule_result = await db.execute(
        select(ContinuityRule)
        .where(ContinuityRule.user_id == user_id)
        .order_by(ContinuityRule.id)
        .limit(MAX_GRAPH_RULES + 1)
    )
    rule_rows = list(rule_result.scalars())
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
    selected_member_rows = list(selected_member_result.scalars())
    if len(selected_member_rows) > MAX_GRAPH_SELECTED_MEMBERS:
        raise _too_large(MAX_GRAPH_SELECTED_MEMBERS)
    selected_member_issue_ids = {
        rule_id: tuple(member.issue_id for member in members)
        for rule_id, members in _group_rows(
            selected_member_rows, lambda member: member.rule_id
        ).items()
    }

    return _GraphSnapshot(
        threads=threads,
        issues=issues,
        groups=groups,
        group_memberships=group_memberships,
        rules=rules,
        rules_by_target=rules_by_target,
        thread_issue_ids=thread_issue_ids,
        selected_member_issue_ids=selected_member_issue_ids,
    )


def _group_issue_ids(group_id: int, snapshot: _GraphSnapshot) -> list[int]:
    """Return all issue IDs represented by a crossover, including thread memberships."""
    memberships = snapshot.group_memberships.get(group_id, ())
    issue_ids = {membership.issue_id for membership in memberships if membership.issue_id}
    thread_ids = {membership.thread_id for membership in memberships if membership.thread_id}
    for thread_id in thread_ids:
        issue_ids.update(snapshot.thread_issue_ids.get(thread_id, ()))
    return sorted(issue_ids)


def _source_label(rule: ContinuityRule, snapshot: _GraphSnapshot) -> str:
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


def _is_read(issue_id: int, snapshot: _GraphSnapshot) -> bool:
    """Return whether one owned issue is read."""
    issue = snapshot.issues.get(issue_id)
    return issue is not None and issue.status == "read"


def _evaluate_rule(rule: ContinuityRule, snapshot: _GraphSnapshot) -> ContinuityBlocker | None:
    """Return a blocker when one direct rule's satisfaction policy is not met."""
    causing_issue_ids: list[int] = []
    causing_member_issue_ids: list[int] = []

    if rule.satisfaction_type == "item_read":
        if rule.source_type == "issue":
            causing_issue_ids = [] if _is_read(rule.source_id, snapshot) else [rule.source_id]
        else:
            member_ids = _group_issue_ids(rule.source_id, snapshot)
            causing_member_issue_ids = [
                issue_id for issue_id in member_ids if not _is_read(issue_id, snapshot)
            ]
    elif rule.satisfaction_type == "all_members_read":
        if rule.source_type == "crossover":
            member_ids = _group_issue_ids(rule.source_id, snapshot)
            causing_member_issue_ids = [
                issue_id for issue_id in member_ids if not _is_read(issue_id, snapshot)
            ]
        else:
            causing_issue_ids = [] if _is_read(rule.source_id, snapshot) else [rule.source_id]
    elif rule.satisfaction_type == "checkpoint":
        checkpoint_id = rule.checkpoint_issue_id
        if checkpoint_id is not None and not _is_read(checkpoint_id, snapshot):
            causing_issue_ids = [checkpoint_id]
    else:
        selected_ids = snapshot.selected_member_issue_ids.get(rule.id, ())
        causing_member_issue_ids = [
            issue_id for issue_id in selected_ids if not _is_read(issue_id, snapshot)
        ]

    if not causing_issue_ids and not causing_member_issue_ids:
        return None
    return ContinuityBlocker(
        rule_id=rule.id,
        source_type=rule.source_type,
        source_id=rule.source_id,
        source_label=_source_label(rule, snapshot),
        satisfaction_type=rule.satisfaction_type,
        causing_issue_ids=causing_issue_ids,
        causing_member_issue_ids=causing_member_issue_ids,
        note=rule.note,
    )


def _direct_blockers(
    node_type: str,
    node_id: int,
    snapshot: _GraphSnapshot,
) -> list[ContinuityBlocker]:
    """Evaluate rules directly targeting one issue or crossover node."""
    blockers: list[ContinuityBlocker] = []
    for rule in snapshot.rules_by_target.get((node_type, node_id), ()):
        blocker = _evaluate_rule(rule, snapshot)
        if blocker is not None:
            blockers.append(blocker)
    return blockers


def _issue_readiness(issue_id: int, snapshot: _GraphSnapshot) -> list[ContinuityBlocker]:
    """Return direct blockers for one issue."""
    return _direct_blockers("issue", issue_id, snapshot)


def _crossover_readiness(group_id: int, snapshot: _GraphSnapshot) -> list[ContinuityBlocker]:
    """Return direct crossover blockers plus blockers on unread member issues."""
    blockers = _direct_blockers("crossover", group_id, snapshot)
    seen_rule_ids = {blocker.rule_id for blocker in blockers}
    for issue_id in _group_issue_ids(group_id, snapshot):
        if _is_read(issue_id, snapshot):
            continue
        for blocker in _issue_readiness(issue_id, snapshot):
            if blocker.rule_id not in seen_rule_ids:
                blockers.append(blocker)
                seen_rule_ids.add(blocker.rule_id)
    blockers.sort(key=lambda blocker: blocker.rule_id)
    return blockers


async def evaluate_continuity_readiness(
    db: AsyncSession,
    *,
    user_id: int,
    node_type: ContinuityReadinessNodeType,
    node_id: int,
) -> ContinuityReadinessResponse:
    """Evaluate direct readiness for an owned issue, thread, or crossover.

    Args:
        db: Database session used to load the authenticated user's continuity graph.
        user_id: Authenticated user whose owned graph should be evaluated.
        node_type: Type of owned node to evaluate.
        node_id: Identifier of the owned node to evaluate.

    Returns:
        Structured readiness state and any unsatisfied direct blockers.
    """
    snapshot = await _load_snapshot(db, user_id)
    evaluated_issue_id: int | None = None

    if node_type == "issue":
        issue = snapshot.issues.get(node_id)
        if issue is None:
            raise HTTPException(status_code=404, detail=f"Issue {node_id} not found")
        blockers = _issue_readiness(node_id, snapshot)
    elif node_type == "thread":
        thread = snapshot.threads.get(node_id)
        if thread is None:
            raise HTTPException(status_code=404, detail=f"Thread {node_id} not found")
        evaluated_issue_id = thread.next_unread_issue_id
        blockers = (
            _issue_readiness(evaluated_issue_id, snapshot)
            if evaluated_issue_id is not None
            else []
        )
    else:
        if node_id not in snapshot.groups:
            raise HTTPException(status_code=404, detail=f"Crossover {node_id} not found")
        blockers = _crossover_readiness(node_id, snapshot)

    return ContinuityReadinessResponse(
        node_type=node_type,
        node_id=node_id,
        is_readable=not blockers,
        evaluated_issue_id=evaluated_issue_id,
        blockers=blockers,
    )

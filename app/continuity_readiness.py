"""Bounded direct readiness evaluation for generalized continuity rules."""

from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.continuity_rule import ContinuityRule
from app.models.dependency_group import DependencyGroup
from app.models.issue import Issue
from app.models.thread import Thread
from app.schemas.continuity_readiness import (
    ContinuityBlocker,
    ContinuityReadinessNodeType,
    ContinuityReadinessResponse,
)

MAX_GRAPH_ISSUES = 10_000
MAX_GRAPH_RULES = 5_000


@dataclass(frozen=True)
class _GraphSnapshot:
    """User-owned continuity data loaded in a bounded set of queries."""

    threads: dict[int, Thread]
    issues: dict[int, Issue]
    groups: dict[int, DependencyGroup]
    rules: tuple[ContinuityRule, ...]


async def _load_snapshot(db: AsyncSession, user_id: int) -> _GraphSnapshot:
    """Load the authenticated user's direct-readiness graph without per-row queries."""
    thread_result = await db.execute(select(Thread).where(Thread.user_id == user_id))
    threads = {thread.id: thread for thread in thread_result.scalars()}

    issue_result = await db.execute(
        select(Issue)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Thread.user_id == user_id)
        .order_by(Issue.id)
        .limit(MAX_GRAPH_ISSUES + 1)
    )
    issues_list = list(issue_result.scalars())
    if len(issues_list) > MAX_GRAPH_ISSUES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "continuity_graph_too_large", "limit": MAX_GRAPH_ISSUES},
        )
    issues = {issue.id: issue for issue in issues_list}

    group_result = await db.execute(
        select(DependencyGroup)
        .options(selectinload(DependencyGroup.memberships))
        .where(DependencyGroup.user_id == user_id)
        .order_by(DependencyGroup.id)
    )
    groups = {group.id: group for group in group_result.scalars()}

    rule_result = await db.execute(
        select(ContinuityRule)
        .options(selectinload(ContinuityRule.selected_members))
        .where(ContinuityRule.user_id == user_id)
        .order_by(ContinuityRule.id)
        .limit(MAX_GRAPH_RULES + 1)
    )
    rules = tuple(rule_result.scalars())
    if len(rules) > MAX_GRAPH_RULES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "continuity_graph_too_large", "limit": MAX_GRAPH_RULES},
        )
    return _GraphSnapshot(threads=threads, issues=issues, groups=groups, rules=rules)


def _group_issue_ids(group: DependencyGroup, snapshot: _GraphSnapshot) -> list[int]:
    """Return all issue IDs represented by a crossover, including thread memberships."""
    issue_ids = {membership.issue_id for membership in group.memberships if membership.issue_id}
    thread_ids = {membership.thread_id for membership in group.memberships if membership.thread_id}
    issue_ids.update(
        issue.id for issue in snapshot.issues.values() if issue.thread_id in thread_ids
    )
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
            member_ids = _group_issue_ids(snapshot.groups[rule.source_id], snapshot)
            causing_member_issue_ids = [
                issue_id for issue_id in member_ids if not _is_read(issue_id, snapshot)
            ]
    elif rule.satisfaction_type == "all_members_read":
        if rule.source_type == "crossover":
            member_ids = _group_issue_ids(snapshot.groups[rule.source_id], snapshot)
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
        selected_ids = sorted(member.issue_id for member in rule.selected_members)
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
    for rule in snapshot.rules:
        if rule.target_type != node_type or rule.target_id != node_id:
            continue
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
    group = snapshot.groups[group_id]
    seen_rule_ids = {blocker.rule_id for blocker in blockers}
    for issue_id in _group_issue_ids(group, snapshot):
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
    """Evaluate direct readiness for an owned issue, thread, or crossover."""
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

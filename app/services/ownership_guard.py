"""Central reader-ownership validation for graph and library write boundaries.

Issue #3225. Every write path that links personal rows (issues, threads,
dependencies, plan membership, session pending pointers, tag assignments)
funnels its ownership predicate through this module so cross-reader writes
are rejected in one place with one semantics.

Ownership authority:

- A reader owns ``Thread`` rows via ``threads.user_id``. An ``Issue`` is
  owned exactly when its parent thread is owned (join-through-thread).
- A ``Thread.next_unread_issue_id`` frontier must reference an ``Issue``
  whose ``thread_id`` is that exact thread (:func:`require_frontier_in_thread`;
  DB-enforced by ``fk_threads_frontier_same_thread``).
- Shared catalog links (``issues.catalog_issue_id``,
  ``threads.catalog_series_id``) are **never** authorization evidence: two
  readers may reference one ``CatalogIssue`` while their personal ``Issue``
  rows stay distinct. No check in this module consults catalog columns.
- Polymorphic ``tag_assignments(target_type, target_id)`` cannot use a
  database foreign key (three unrelated target tables share one column), so
  :func:`target_owner_id` is the typed enforcement point and every
  assignment path must call it.
- Cross-user graph edges stay application-enforced: ``issues`` and
  ``dependencies`` carry no ``user_id``, and denormalizing one would duplicate
  the single ``threads.user_id`` authority and risk divergence. Violation
  detection (:func:`detect_violations`) reports counts and IDs only — never
  titles, notes, ratings, or payloads.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.reading_plan_membership import ReadingPlanDependency, ReadingPlanIssue
from app.models.reading_session import ReadingSession
from app.models.tag import Tag, TagAssignment
from app.models.thread import Thread
from app.repositories import continuity_repository, issue_repository, thread_repository
from app.services.errors import InvalidRequestError

#: Target types that resolve ownership through the owning thread.
_ISSUE_TARGET_TYPES = frozenset({"Issue"})


@dataclass
class SessionPendingStatus:
    """Ownership state of one reading session's pending pointers."""

    pending_thread_owned: bool = True
    pending_issue_owned: bool = True
    issue_in_pending_thread: bool = True

    @property
    def consistent(self) -> bool:
        """Return whether every set pointer is owned and paired."""
        return (
            self.pending_thread_owned
            and self.pending_issue_owned
            and self.issue_in_pending_thread
        )


@dataclass
class OwnershipViolationReport:
    """Redacted violation inventory: counts and row IDs only.

    No titles, notes, ratings, event payloads, or credentials are ever
    included — IDs are sufficient to triage ownership drift.
    """

    frontier_thread_ids: list[int] = field(default_factory=list)
    cross_user_dependency_ids: list[int] = field(default_factory=list)
    plan_issue_pairs: list[list[int]] = field(default_factory=list)
    plan_dependency_pairs: list[list[int]] = field(default_factory=list)
    session_pending_thread_ids: list[int] = field(default_factory=list)
    session_pending_issue_ids: list[int] = field(default_factory=list)
    session_pending_mismatch_ids: list[int] = field(default_factory=list)
    private_tag_assignment_ids: list[int] = field(default_factory=list)

    @property
    def has_violations(self) -> bool:
        """Return whether any category reported a violation."""
        return any(
            (
                self.frontier_thread_ids,
                self.cross_user_dependency_ids,
                self.plan_issue_pairs,
                self.plan_dependency_pairs,
                self.session_pending_thread_ids,
                self.session_pending_issue_ids,
                self.session_pending_mismatch_ids,
                self.private_tag_assignment_ids,
            )
        )

    def to_redacted_dict(self) -> dict[str, object]:
        """Serialize counts and IDs without any private payload content."""
        return {
            "frontier_thread_ids": sorted(self.frontier_thread_ids),
            "frontier_violation_count": len(self.frontier_thread_ids),
            "cross_user_dependency_ids": sorted(self.cross_user_dependency_ids),
            "cross_user_dependency_count": len(self.cross_user_dependency_ids),
            "plan_issue_pairs": sorted(self.plan_issue_pairs),
            "plan_issue_violation_count": len(self.plan_issue_pairs),
            "plan_dependency_pairs": sorted(self.plan_dependency_pairs),
            "plan_dependency_violation_count": len(self.plan_dependency_pairs),
            "session_pending_thread_ids": sorted(self.session_pending_thread_ids),
            "session_pending_issue_ids": sorted(self.session_pending_issue_ids),
            "session_pending_mismatch_ids": sorted(self.session_pending_mismatch_ids),
            "private_tag_assignment_ids": sorted(self.private_tag_assignment_ids),
            "private_tag_violation_count": len(self.private_tag_assignment_ids),
            "has_violations": self.has_violations,
        }


async def issues_owned_by(
    db: AsyncSession, user_id: int, issue_ids: list[int]
) -> dict[int, Issue]:
    """Return the subset of issues owned by the user, keyed by issue ID.

    Ownership resolves join-through-thread; shared ``catalog_issue_id``
    values are ignored so a shared catalog row never grants ownership.

    Args:
        db: Database session.
        user_id: Owner that must own each issue's parent thread.
        issue_ids: Candidate issue primary keys.

    Returns:
        Mapping of owned issue ID to issue for every owned, existing ID.
    """
    unique_ids = sorted({issue_id for issue_id in issue_ids if issue_id > 0})
    if not unique_ids:
        return {}
    result = await db.execute(
        select(Issue)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Issue.id.in_(unique_ids), Thread.user_id == user_id)
    )
    return {issue.id: issue for issue in result.scalars().all()}


async def require_dependency_endpoints_owned(
    db: AsyncSession, user_id: int, source_issue_id: int, target_issue_id: int
) -> tuple[Issue, Issue]:
    """Require both dependency endpoints to be owned by one reader.

    Args:
        db: Database session.
        user_id: Reader that must own both endpoint threads.
        source_issue_id: Prerequisite issue.
        target_issue_id: Blocked issue.

    Returns:
        The owned ``(source, target)`` issues.

    Raises:
        HTTPException: 404 ``Issue not found`` when either endpoint is
            missing or owned by another reader — even when both readers
            share one ``CatalogIssue``.
    """
    owned = await issues_owned_by(db, user_id, [source_issue_id, target_issue_id])
    source = owned.get(source_issue_id)
    target = owned.get(target_issue_id)
    if source is None or target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    return source, target


async def require_frontier_in_thread(
    db: AsyncSession, thread_id: int, issue_id: int | None
) -> Issue | None:
    """Require a frontier pointer to reference the exact thread's issue.

    Args:
        db: Database session.
        thread_id: Thread that must own the frontier issue.
        issue_id: Candidate ``next_unread_issue_id`` (``None`` passes).

    Returns:
        The frontier issue, or ``None`` when no pointer is set.

    Raises:
        HTTPException: 422 ``frontier_issue_mismatch`` when the issue is
            missing or belongs to a different thread — including another
            thread of the same reader.
    """
    if issue_id is None:
        return None
    result = await db.execute(
        select(Issue).where(Issue.id == issue_id, Issue.thread_id == thread_id)
    )
    issue = result.scalar_one_or_none()
    if issue is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "frontier_issue_mismatch",
                "thread_id": thread_id,
                "issue_id": issue_id,
            },
        )
    return issue


async def require_plan_issue_refs_owned(
    db: AsyncSession, *, user_id: int, refs: dict[int, str]
) -> None:
    """Require every plan issue reference to be owned by the plan owner.

    Args:
        db: Database session.
        user_id: Plan owner that must own every referenced issue's thread.
        refs: Mapping of issue ID to plan node ID for error reporting.

    Raises:
        HTTPException: 422 ``dangling_plan_reference`` naming the first
            node whose issue is missing or owned by another reader.
    """
    if not refs:
        return
    owned_ids = await continuity_repository.owned_issue_ids_for_user(
        db, user_id, sorted(refs)
    )
    for issue_id in sorted(refs):
        if issue_id not in owned_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "dangling_plan_reference", "node_id": refs[issue_id]},
            )


async def session_pending_status(
    db: AsyncSession, session: ReadingSession
) -> SessionPendingStatus:
    """Inspect one session's pending pointers without raising.

    Args:
        db: Database session.
        session: Session whose pointers are inspected.

    Returns:
        Ownership/pairing flags for the set pointers.
    """
    result = SessionPendingStatus()
    pending_thread: Thread | None = None
    if session.pending_thread_id is not None:
        pending_thread = await thread_repository.find_owned(
            db, session.user_id, session.pending_thread_id
        )
        result.pending_thread_owned = pending_thread is not None
    if session.pending_issue_id is not None:
        owned_issue = await issue_repository.find_owned(
            db, session.user_id, session.pending_issue_id
        )
        result.pending_issue_owned = owned_issue is not None
        if (
            owned_issue is not None
            and pending_thread is not None
            and owned_issue.thread_id != pending_thread.id
        ):
            result.issue_in_pending_thread = False
    return result


async def require_session_pending_consistent(
    db: AsyncSession, session: ReadingSession
) -> None:
    """Require a session's pending pointers to be owned and paired.

    Args:
        db: Database session.
        session: Session whose pointers must be consistent.

    Raises:
        HTTPException: 422 ``dangling_session_reference`` when a set
            pending thread/issue is owned by another reader, or the
            pending issue lives in a different thread than the pending
            thread.
    """
    pending_status = await session_pending_status(db, session)
    if not pending_status.pending_thread_owned:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "dangling_session_reference",
                "pointer": "pending_thread_id",
                "session_id": session.id,
            },
        )
    if not pending_status.pending_issue_owned:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "dangling_session_reference",
                "pointer": "pending_issue_id",
                "session_id": session.id,
            },
        )
    if not pending_status.issue_in_pending_thread:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "dangling_session_reference",
                "pointer": "pending_issue_thread_mismatch",
                "session_id": session.id,
            },
        )


async def target_owner_id(
    db: AsyncSession, target_type: str, target_id: int
) -> int | None:
    """Resolve the owning reader of a polymorphic tag target.

    A database foreign key cannot enforce ``(target_type, target_id)``
    because three unrelated tables share the column pair, so this typed
    lookup is the enforcement point every assignment path must use.
    Ownership resolves join-through-thread for issues; catalog links are
    never consulted.

    Args:
        db: Database session.
        target_type: One of ``Issue``, ``Thread``, ``ContinuityPlan``.
        target_id: Primary key of the target row.

    Returns:
        The owning user ID, or ``None`` when the target does not exist.

    Raises:
        InvalidRequestError: When ``target_type`` is not a known type.
    """
    if target_type in _ISSUE_TARGET_TYPES:
        row = await db.execute(
            select(Thread.user_id)
            .join(Issue, Issue.thread_id == Thread.id)
            .where(Issue.id == target_id)
        )
        return row.scalar_one_or_none()
    if target_type == "Thread":
        return await db.scalar(select(Thread.user_id).where(Thread.id == target_id))
    if target_type == "ContinuityPlan":
        return await db.scalar(
            select(ContinuityPlan.user_id).where(ContinuityPlan.id == target_id)
        )
    raise InvalidRequestError(
        f"Unsupported target type '{target_type}'. Supported types: "
        "Issue, Thread, ContinuityPlan"
    )


async def detect_violations(db: AsyncSession) -> OwnershipViolationReport:
    """Detect reader-ownership violations across graph/library boundaries.

    Read-only: issues SELECT statements only and returns row IDs plus
    counts — never titles, notes, ratings, event payloads, or credentials.

    Args:
        db: Database session.

    Returns:
        Redacted violation inventory.
    """
    report = OwnershipViolationReport()

    frontier_rows = (
        await db.execute(
            select(Thread.id)
            .outerjoin(
                Issue,
                (Issue.id == Thread.next_unread_issue_id)
                & (Issue.thread_id == Thread.id),
            )
            .where(Thread.next_unread_issue_id.is_not(None), Issue.id.is_(None))
        )
    ).scalars().all()
    report.frontier_thread_ids = sorted({int(thread_id) for thread_id in frontier_rows})

    source_thread = Thread.__table__.alias("source_thread")
    target_thread = Thread.__table__.alias("target_thread")
    source_issue = Issue.__table__.alias("source_issue")
    target_issue = Issue.__table__.alias("target_issue")
    dep_rows = (
        await db.execute(
            select(Dependency.id)
            .join(source_issue, source_issue.c.id == Dependency.source_issue_id)
            .join(source_thread, source_thread.c.id == source_issue.c.thread_id)
            .join(target_issue, target_issue.c.id == Dependency.target_issue_id)
            .join(target_thread, target_thread.c.id == target_issue.c.thread_id)
            .where(source_thread.c.user_id != target_thread.c.user_id)
        )
    ).scalars().all()
    report.cross_user_dependency_ids = sorted({int(dep_id) for dep_id in dep_rows})

    member_rows = (
        await db.execute(
            select(ReadingPlanIssue.plan_id, ReadingPlanIssue.issue_id)
            .join(ContinuityPlan, ContinuityPlan.id == ReadingPlanIssue.plan_id)
            .join(Issue, Issue.id == ReadingPlanIssue.issue_id)
            .join(Thread, Thread.id == Issue.thread_id)
            .where(Thread.user_id != ContinuityPlan.user_id)
        )
    ).all()
    report.plan_issue_pairs = sorted(
        [
            list(pair)
            for pair in {
                (int(plan_id), int(issue_id)) for plan_id, issue_id in member_rows
            }
        ]
    )

    plan_dep_rows = (
        await db.execute(
            select(ReadingPlanDependency.plan_id, ReadingPlanDependency.dependency_id)
            .join(
                ContinuityPlan, ContinuityPlan.id == ReadingPlanDependency.plan_id
            )
            .join(Dependency, Dependency.id == ReadingPlanDependency.dependency_id)
            .join(Issue, Issue.id == Dependency.source_issue_id)
            .join(Thread, Thread.id == Issue.thread_id)
            .where(Thread.user_id != ContinuityPlan.user_id)
        )
    ).all()
    plan_dep_pairs: set[tuple[int, int]] = {
        (int(plan_id), int(dep_id)) for plan_id, dep_id in plan_dep_rows
    }
    plan_dep_target_rows = (
        await db.execute(
            select(ReadingPlanDependency.plan_id, ReadingPlanDependency.dependency_id)
            .join(
                ContinuityPlan, ContinuityPlan.id == ReadingPlanDependency.plan_id
            )
            .join(Dependency, Dependency.id == ReadingPlanDependency.dependency_id)
            .join(Issue, Issue.id == Dependency.target_issue_id)
            .join(Thread, Thread.id == Issue.thread_id)
            .where(Thread.user_id != ContinuityPlan.user_id)
        )
    ).all()
    plan_dep_pairs.update(
        (int(plan_id), int(dep_id)) for plan_id, dep_id in plan_dep_target_rows
    )
    report.plan_dependency_pairs = sorted([list(pair) for pair in plan_dep_pairs])

    pending_thread_rows = (
        await db.execute(
            select(ReadingSession.id)
            .join(Thread, Thread.id == ReadingSession.pending_thread_id)
            .where(
                ReadingSession.pending_thread_id.is_not(None),
                Thread.user_id != ReadingSession.user_id,
            )
        )
    ).scalars().all()
    report.session_pending_thread_ids = sorted(
        {int(session_id) for session_id in pending_thread_rows}
    )

    pending_issue_rows = (
        await db.execute(
            select(ReadingSession.id)
            .join(Issue, Issue.id == ReadingSession.pending_issue_id)
            .join(Thread, Thread.id == Issue.thread_id)
            .where(
                ReadingSession.pending_issue_id.is_not(None),
                Thread.user_id != ReadingSession.user_id,
            )
        )
    ).scalars().all()
    report.session_pending_issue_ids = sorted(
        {int(session_id) for session_id in pending_issue_rows}
    )

    mismatch_rows = (
        await db.execute(
            select(ReadingSession.id)
            .join(Issue, Issue.id == ReadingSession.pending_issue_id)
            .where(
                ReadingSession.pending_issue_id.is_not(None),
                ReadingSession.pending_thread_id.is_not(None),
                Issue.thread_id != ReadingSession.pending_thread_id,
            )
        )
    ).scalars().all()
    report.session_pending_mismatch_ids = sorted(
        {int(session_id) for session_id in mismatch_rows}
    )

    private_rows = (
        await db.execute(
            select(TagAssignment.id)
            .join(Tag, Tag.id == TagAssignment.tag_id)
            .join(Thread, Thread.id == TagAssignment.target_id)
            .where(
                Tag.scope == "private",
                TagAssignment.target_type == "Thread",
                Thread.user_id != Tag.owner_user_id,
            )
        )
    ).scalars().all()
    private_ids: set[int] = {int(row) for row in private_rows}
    private_issue_rows = (
        await db.execute(
            select(TagAssignment.id)
            .join(Tag, Tag.id == TagAssignment.tag_id)
            .join(Issue, Issue.id == TagAssignment.target_id)
            .join(Thread, Thread.id == Issue.thread_id)
            .where(
                Tag.scope == "private",
                TagAssignment.target_type == "Issue",
                Thread.user_id != Tag.owner_user_id,
            )
        )
    ).scalars().all()
    private_ids.update(int(row) for row in private_issue_rows)
    private_plan_rows = (
        await db.execute(
            select(TagAssignment.id)
            .join(Tag, Tag.id == TagAssignment.tag_id)
            .join(ContinuityPlan, ContinuityPlan.id == TagAssignment.target_id)
            .where(
                Tag.scope == "private",
                TagAssignment.target_type == "ContinuityPlan",
                ContinuityPlan.user_id != Tag.owner_user_id,
            )
        )
    ).scalars().all()
    private_ids.update(int(row) for row in private_plan_rows)
    report.private_tag_assignment_ids = sorted(private_ids)

    return report

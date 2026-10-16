"""Read-only scalar evidence for comparing current and Option E eligibility."""

from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dependency, Issue, Thread
from app.repositories import reading_list_authoring_repository as authoring
from app.services.reading_list_evaluator import (
    ReadingIssue,
    ReadingList,
    ReadingListEntry,
    ReadingPrerequisite,
    ReadingThread,
)


@dataclass(frozen=True, slots=True)
class StoredThreadEligibility:
    """Current queue predicates and stored frontier, detached from the ORM."""

    thread_id: int
    next_issue_id: int | None
    is_blocked: bool
    queue_position: int


@dataclass(frozen=True, slots=True)
class UnresolvedReadingReference:
    """An owned object with an unresolved endpoint; no foreign data is exposed."""

    kind: str
    object_id: int


@dataclass(frozen=True, slots=True)
class ShadowReadingInputs:
    """Complete detached inputs, including diagnostics that prevent trust."""

    user_id: int
    threads: tuple[ReadingThread, ...]
    issues: tuple[ReadingIssue, ...]
    lists: tuple[ReadingList, ...]
    prerequisites: tuple[ReadingPrerequisite, ...]
    excluded_issue_ids: frozenset[int]
    stored: tuple[StoredThreadEligibility, ...]
    unresolved: tuple[UnresolvedReadingReference, ...]
    inert_dependency_count: int


async def load_shadow_inputs(db: AsyncSession, user_id: int) -> ShadowReadingInputs:
    """Read owner-scoped evidence in a constant number of bulk queries.

    Callers needing a durable census must use a repeatable-read, read-only
    transaction. No cache, compiled plan membership or pointer selects the new
    frontier. Foreign endpoints are diagnosed, never silently dropped or loaded.
    Autoflush is disabled even when the caller has pending changes.

    Args:
        db: Current read transaction.
        user_id: Reader whose authored constraints are being compared.

    Returns:
        Immutable inputs for the pure shadow diagnostic.
    """
    with db.no_autoflush:
        threads = await authoring.load_threads(db, user_id)
        issues = await authoring.load_issues(db, user_id)
        lists = await authoring.load_lists(db, user_id)
        entries = await authoring.load_entries(db, user_id)
        excluded = await authoring.load_excluded_issue_ids(db, user_id, issues)
        owned = (
            select(Issue.id)
            .join(Thread, Thread.id == Issue.thread_id)
            .where(Thread.user_id == user_id)
        )
        touching = or_(Dependency.source_issue_id.in_(owned), Dependency.target_issue_id.in_(owned))
        enforced = or_(Dependency.note.is_(None), Dependency.note.not_like("cbl-order:%"))
        dependencies = list(
            (
                await db.scalars(
                    select(Dependency).where(touching, enforced).order_by(Dependency.id)
                )
            ).all()
        )
        inert_count = int(
            (
                await db.scalar(
                    select(func.count(Dependency.id)).where(
                        touching, Dependency.note.like("cbl-order:%")
                    )
                )
            )
            or 0
        )
        issue_ids = {issue.id for issue in issues}
        unresolved: list[UnresolvedReadingReference] = []
        by_list: dict[int, list[ReadingListEntry]] = {}
        for entry in entries:
            if entry.issue_id not in issue_ids:
                unresolved.append(UnresolvedReadingReference("list_entry", entry.id))
            by_list.setdefault(entry.list_id, []).append(
                ReadingListEntry(entry.issue_id, entry.gate, entry.skipped)
            )
        for row in dependencies:
            if row.source_issue_id not in issue_ids or row.target_issue_id not in issue_ids:
                unresolved.append(UnresolvedReadingReference("prerequisite", row.id))
        return ShadowReadingInputs(
            user_id=user_id,
            threads=tuple(ReadingThread(row.id, row.status) for row in threads),
            issues=tuple(
                ReadingIssue(row.id, row.thread_id, row.position, row.status) for row in issues
            ),
            lists=tuple(
                ReadingList(row.id, row.mode, tuple(by_list.get(row.id, ())))
                for row in sorted(lists, key=lambda row: row.id)
            ),
            prerequisites=tuple(
                ReadingPrerequisite(
                    row.id,
                    row.source_issue_id,
                    row.target_issue_id,
                    "converted",
                    ("historical classification unknown",),
                )
                for row in dependencies
            ),
            excluded_issue_ids=excluded,
            stored=tuple(
                StoredThreadEligibility(
                    row.id, row.next_unread_issue_id, row.is_blocked, row.queue_position
                )
                for row in sorted(threads, key=lambda row: row.id)
            ),
            unresolved=tuple(sorted(unresolved, key=lambda row: (row.kind, row.object_id))),
            inert_dependency_count=inert_count,
        )

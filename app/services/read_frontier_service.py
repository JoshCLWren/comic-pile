"""Read-only canonical Thread frontiers for Option E shadow and census callers."""

from collections.abc import Collection
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import issue_repository


@dataclass(frozen=True)
class ThreadReadFrontier:
    """Derived frontier and comparable stored-pointer diagnostics, never persisted."""

    thread_id: int
    next_issue_id: int | None
    stored_next_issue_id: int | None
    stored_pointer_in_thread: bool | None
    issue_count: int
    unread_count: int
    excluded_unread_count: int

    @property
    def pointer_mismatch(self) -> bool:
        """Return whether the cached pointer differs from the canonical frontier."""
        return self.next_issue_id != self.stored_next_issue_id


async def derive_read_frontiers(
    db: AsyncSession,
    user_id: int,
    *,
    excluded_issue_ids: Collection[int] = (),
) -> dict[int, ThreadReadFrontier]:
    """Derive each owned active Thread's first unread, non-excluded issue.

    Reads scalar storage values in one query with autoflush disabled. Does not
    consult cached counters, blocking flags or pointers to choose a candidate,
    and does not change Thread status, progress, Issue state or Roll. Only
    ``read`` is complete; other states remain unread, as in prerequisites. Missing
    threads are absent; empty and fully read threads have no candidate.

    Args:
        db: Database session.
        user_id: Reader whose active threads are inspected.
        excluded_issue_ids: Global collection exclusions supplied by the caller,
            not list-local skips. Foreign issue IDs have no effect.

    Returns:
        Deterministic thread-ID mapping with frontier and pointer diagnostics.
        A non-null pointer not owned by its Thread is marked invalid without
        looking up or exposing the pointed-to issue's foreign owner.
    """
    excluded = frozenset(excluded_issue_ids)
    rows = await issue_repository.active_frontier_rows(db, user_id)
    grouped: dict[int, list[tuple[int, int, str]]] = {}
    pointers: dict[int, int | None] = {}
    for thread_id, pointer, issue_id, position, status in rows:
        pointers[thread_id] = pointer
        issues = grouped.setdefault(thread_id, [])
        if issue_id is not None and position is not None and status is not None:
            issues.append((issue_id, position, status))

    frontiers: dict[int, ThreadReadFrontier] = {}
    for thread_id in sorted(grouped):
        issues = sorted(grouped[thread_id], key=lambda issue: (issue[1], issue[0]))
        unread = [issue_id for issue_id, _, status in issues if status != "read"]
        pointer = pointers[thread_id]
        frontiers[thread_id] = ThreadReadFrontier(
            thread_id=thread_id,
            next_issue_id=next((issue_id for issue_id in unread if issue_id not in excluded), None),
            stored_next_issue_id=pointer,
            stored_pointer_in_thread=(
                None if pointer is None else any(issue[0] == pointer for issue in issues)
            ),
            issue_count=len(issues),
            unread_count=len(unread),
            excluded_unread_count=sum(issue_id in excluded for issue_id in unread),
        )
    return frontiers

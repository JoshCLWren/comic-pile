"""Atomic Option E authoring validation without materializing dependency edges."""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import reading_list_authoring_repository as repository
from app.schemas.custom_cbl import ReadingListPredecessorChange
from app.services.reading_list_cycle_validator import (
    ReadingCycleError,
    validate_reading_constraints,
)
from app.services.reading_list_evaluator import (
    ReadingIssue,
    ReadingList,
    ReadingListEntry,
    ReadingPrerequisite,
    ReadingSnapshot,
    ReadingThread,
)


async def load_authoring_snapshot(
    db: AsyncSession, user_id: int
) -> tuple[ReadingSnapshot, dict[int, str]]:
    """Read complete constraints without classifying historical dependencies.

    Args:
        db: Current authoring transaction.
        user_id: Reader whose complete constraint graph is loaded.

    Returns:
        Snapshot and display names, sharing a single load of owned Issues.
    """
    threads = await repository.load_threads(db, user_id)
    issues = await repository.load_issues(db, user_id)
    lists = await repository.load_lists(db, user_id)
    entries = await repository.load_entries(db, user_id)
    requirements = await repository.load_requirements(db, user_id)
    excluded = await repository.load_excluded_issue_ids(db, user_id, issues)
    if any(row.source_issue_id in excluded for row in requirements):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "reading_list_invalid_constraints",
                "message": "Collection exclusion strands an explicit prerequisite",
            },
        )
    by_list: dict[int, list[ReadingListEntry]] = {}
    for entry in entries:
        by_list.setdefault(entry.list_id, []).append(
            ReadingListEntry(entry.issue_id, entry.gate, entry.skipped)
        )
    snapshot = ReadingSnapshot(
        user_id=user_id,
        threads=tuple(ReadingThread(t.id, t.status, t.title) for t in threads),
        issues=tuple(ReadingIssue(i.id, i.thread_id, i.position, i.status) for i in issues),
        lists=tuple(
            ReadingList(
                row.id,
                row.mode,
                tuple(by_list.get(row.id, ())),
                row.name,
            )
            for row in lists
        ),
        prerequisites=tuple(
            ReadingPrerequisite(
                row.id,
                row.source_issue_id,
                row.target_issue_id,
                "converted",
                ("historical classification unknown", row.note or ""),
            )
            for row in requirements
        ),
        excluded_issue_ids=excluded,
    )
    thread_names = {thread.id: thread.title for thread in threads}
    names = {issue.id: f"{thread_names[issue.thread_id]} #{issue.issue_number}" for issue in issues}
    return snapshot, names


def _requirements(reading_list: ReadingList) -> dict[int, list[int]]:
    """Describe stored positional constraints, including globally excluded Issues."""
    result: dict[int, list[int]] = {}
    earlier: list[int] = []
    hold: list[int] = []
    for entry in reading_list.entries:
        if entry.skipped:
            continue
        sources = set(hold)
        if reading_list.mode == "strict" or entry.gate == "hold":
            sources.update(earlier)
        if entry.gate == "after_previous" and earlier:
            sources.add(earlier[-1])
        result[entry.issue_id] = [issue_id for issue_id in earlier if issue_id in sources]
        earlier.append(entry.issue_id)
        if entry.gate == "hold":
            hold = list(earlier)
    return result


async def validate_authored_list(
    db: AsyncSession,
    *,
    user_id: int,
    list_id: int,
    before: ReadingList | None,
    confirmed: list[ReadingListPredecessorChange] | None,
) -> tuple[list[ReadingListPredecessorChange], list[str]]:
    """Validate the union and demand exact acknowledgement of retargeted gates.

    Args:
        db: Current authoring transaction, holding the reader's list-write lock.
        user_id: Reader whose complete graph must remain valid.
        list_id: Changed list identifier.
        before: Previous list intent, or None for a new list.
        confirmed: Named predecessor changes acknowledged by the reader.

    Returns:
        Stored-constraint changes and strict partial-Thread warnings.

    Raises:
        HTTPException: For invalid constraints, cycles, or missing confirmation.
    """
    snapshot, names = await load_authoring_snapshot(db, user_id)
    try:
        validate_reading_constraints(snapshot)
    except ReadingCycleError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "reading_list_cycle",
                "message": str(exc),
                "path": [
                    {
                        "source_issue_id": e.source_issue_id,
                        "target_issue_id": e.target_issue_id,
                        "origin": e.origin,
                    }
                    for e in exc.edges
                ],
            },
        ) from exc
    after = next((row for row in snapshot.lists if row.list_id == list_id), None)
    if after is None:
        raise HTTPException(status_code=404, detail="Reading List not found")
    warnings: list[str] = []
    if after.mode == "strict":
        members = {entry.issue_id for entry in after.entries}
        represented = {issue.thread_id for issue in snapshot.issues if issue.issue_id in members}
        omitted_by_thread: dict[int, list[str]] = {}
        for issue in snapshot.issues:
            if (
                issue.thread_id in represented
                and issue.issue_id not in members
                and issue.status != "read"
                and issue.issue_id not in snapshot.excluded_issue_ids
            ):
                omitted_by_thread.setdefault(issue.thread_id, []).append(names[issue.issue_id])
        for thread in snapshot.threads:
            if omitted := omitted_by_thread.get(thread.thread_id):
                warnings.append(
                    f"Strict list omits unread Issues from {thread.name}: " + ", ".join(omitted)
                )
    if before is None:
        return [], warnings
    old = _requirements(before)
    new = _requirements(after)
    changes = [
        ReadingListPredecessorChange(
            issue_id=issue_id,
            issue_name=names[issue_id],
            before_issue_ids=old.get(issue_id, []),
            before_issue_names=[names[i] for i in old.get(issue_id, [])],
            after_issue_ids=new.get(issue_id, []),
            after_issue_names=[names[i] for i in new.get(issue_id, [])],
        )
        for issue_id in sorted(old.keys() | new.keys())
        if old.get(issue_id, []) != new.get(issue_id, [])
    ]

    def confirmation_key(
        change: ReadingListPredecessorChange,
    ) -> tuple[int, tuple[int, ...], tuple[int, ...]]:
        return (
            change.issue_id,
            tuple(sorted(change.before_issue_ids)),
            tuple(sorted(change.after_issue_ids)),
        )

    if changes and sorted(map(confirmation_key, confirmed or [])) != sorted(
        map(confirmation_key, changes)
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "reading_list_predecessor_confirmation_required",
                "predecessor_changes": [change.model_dump() for change in changes],
            },
        )
    return changes, warnings

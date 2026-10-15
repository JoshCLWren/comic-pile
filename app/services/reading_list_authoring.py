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


async def load_authoring_snapshot(db: AsyncSession, user_id: int) -> ReadingSnapshot:
    """Read complete constraints without classifying historical dependencies.

    Args:
        db: Current authoring transaction.
        user_id: Reader whose complete constraint graph is loaded.

    Returns:
        Immutable snapshot with historical requirements marked unknown in memory.
    """
    threads = await repository.load_threads(db, user_id)
    issues = await repository.load_issues(db, user_id)
    lists = await repository.load_lists(db, user_id)
    entries = await repository.load_entries(db, user_id)
    requirements = await repository.load_requirements(db, user_id)
    excluded = await repository.load_excluded_issue_ids(db, user_id)
    try:
        return ReadingSnapshot(
            user_id=user_id,
            threads=tuple(ReadingThread(t.id, t.status, t.title) for t in threads),
            issues=tuple(ReadingIssue(i.id, i.thread_id, i.position, i.status) for i in issues),
            lists=tuple(
                ReadingList(
                    row.id,
                    row.mode,
                    tuple(
                        ReadingListEntry(e.issue_id, e.gate, e.skipped)
                        for e in entries
                        if e.list_id == row.id
                    ),
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
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "reading_list_invalid_constraints",
                "message": str(exc),
            },
        ) from exc


def _requirements(reading_list: ReadingList, excluded: frozenset[int]) -> dict[int, list[int]]:
    """Describe positional requirements independently of current read state."""
    result: dict[int, list[int]] = {}
    earlier: list[int] = []
    hold: list[int] = []
    for entry in reading_list.entries:
        if entry.skipped or entry.issue_id in excluded:
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
) -> list[ReadingListPredecessorChange]:
    """Validate the union and demand exact acknowledgement of retargeted gates.

    Args:
        db: Current authoring transaction, holding the reader's list-write lock.
        user_id: Reader whose complete graph must remain valid.
        list_id: Changed list identifier.
        before: Previous list intent, or None for a new list.
        confirmed: Named predecessor changes acknowledged by the reader.

    Returns:
        Effective named changes for the saved list.

    Raises:
        HTTPException: For invalid constraints, cycles, or missing confirmation.
    """
    snapshot = await load_authoring_snapshot(db, user_id)
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
    after = next(row for row in snapshot.lists if row.list_id == list_id)
    if before is None:
        return []
    old = _requirements(before, snapshot.excluded_issue_ids)
    new = _requirements(after, snapshot.excluded_issue_ids)
    threads = {row.thread_id: row.name for row in snapshot.threads}
    issues = await repository.load_issues(db, user_id)
    names = {i.id: f"{threads[i.thread_id]} #{i.issue_number}" for i in issues}
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
    # Explicit mode/gate edits already express new intent. A placement or skip edit
    # can retarget existing gates without the reader noticing and needs a preview.
    placement_changed = tuple((e.issue_id, e.skipped) for e in before.entries) != tuple(
        (e.issue_id, e.skipped) for e in after.entries
    )
    if changes and placement_changed and confirmed != changes:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "reading_list_predecessor_confirmation_required",
                "predecessor_changes": [change.model_dump() for change in changes],
            },
        )
    return changes

"""Atomic Option E authoring validation without materializing dependency edges."""

from collections.abc import Mapping

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import reading_list_authoring_repository as repository
from app.repositories import reading_overlap_decision_repository as overlap_repository
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
    SeriesOverlapDecision,
)


async def _overlap_decisions_by_list(
    db: AsyncSession,
    user_id: int,
    projected: Mapping[int, tuple[SeriesOverlapDecision, ...]] | None,
) -> dict[int, tuple[SeriesOverlapDecision, ...]]:
    """Resolve the reader-approved overlap decisions of one reader.

    Args:
        db: Current authoring transaction.
        user_id: Reader whose decisions are resolved.
        projected: Complete replacement decision set keyed by Reading List ID.
            None loads the reader's durable decisions.

    Returns:
        Mapping of Reading List ID to its reader-approved overlap decisions.
    """
    if projected is not None:
        return {list_id: tuple(values) for list_id, values in projected.items()}
    records = await overlap_repository.load_overlap_decisions(db, user_id)
    return overlap_repository.group_decisions_by_list(records)


async def load_authoring_snapshot(
    db: AsyncSession,
    user_id: int,
    *,
    overlap_decisions: Mapping[int, tuple[SeriesOverlapDecision, ...]] | None = None,
) -> tuple[ReadingSnapshot, dict[int, str]]:
    """Read complete constraints without classifying historical dependencies.

    Args:
        db: Current authoring transaction.
        user_id: Reader whose complete constraint graph is loaded.
        overlap_decisions: Complete replacement reader-approved overlap
            decisions keyed by Reading List ID. None loads the reader's durable
            decisions; a write path passes its projected set so the validated
            graph is the one the write would create.

    Returns:
        Snapshot and display names, sharing a single load of owned Issues.
    """
    threads = await repository.load_threads(db, user_id)
    issues = await repository.load_issues(db, user_id)
    lists = await repository.load_lists(db, user_id)
    entries = await repository.load_entries(db, user_id)
    requirements = await repository.load_requirements(db, user_id)
    excluded = await repository.load_excluded_issue_ids(db, user_id, issues)
    volume_keys = await overlap_repository.resolve_thread_volume_keys(
        db, user_id, [thread.id for thread in threads]
    )
    decisions = await _overlap_decisions_by_list(db, user_id, overlap_decisions)
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
        threads=tuple(
            ReadingThread(t.id, t.status, t.title, volume_keys.get(t.id)) for t in threads
        ),
        issues=tuple(ReadingIssue(i.id, i.thread_id, i.position, i.status) for i in issues),
        lists=tuple(
            ReadingList(
                row.id,
                row.mode,
                tuple(by_list.get(row.id, ())),
                row.name,
                decisions.get(row.id, ()),
            )
            for row in lists
        ),
        prerequisites=tuple(
            ReadingPrerequisite(
                row.id,
                row.source_issue_id,
                row.target_issue_id,
                row.origin or "converted",
                (row.provenance or "historical classification unknown", row.note or ""),
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
                        "source_issue_name": names.get(
                            e.source_issue_id, f"Issue #{e.source_issue_id}"
                        ),
                        "target_issue_id": e.target_issue_id,
                        "target_issue_name": names.get(
                            e.target_issue_id, f"Issue #{e.target_issue_id}"
                        ),
                        "origin": e.origin,
                        "prerequisite_origin": e.prerequisite_origin,
                        "provenance": list(e.provenance),
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
        # Represented Threads include skipped placements so skipping the only
        # member still warns about the unread material execution ignores.
        placed = {entry.issue_id for entry in after.entries}
        covered = {entry.issue_id for entry in after.entries if not entry.skipped}
        represented = {issue.thread_id for issue in snapshot.issues if issue.issue_id in placed}
        omitted_counts: dict[int, int] = {}
        samples: dict[int, list[str]] = {}
        for issue in snapshot.issues:
            if (
                issue.thread_id in represented
                and issue.issue_id not in covered
                and issue.status != "read"
                and issue.issue_id not in snapshot.excluded_issue_ids
            ):
                omitted_counts[issue.thread_id] = omitted_counts.get(issue.thread_id, 0) + 1
                sample = samples.setdefault(issue.thread_id, [])
                if len(sample) < 5:
                    sample.append(names[issue.issue_id][:80])
        affected = [thread for thread in snapshot.threads if thread.thread_id in omitted_counts]
        for thread in affected[:10]:
            count = omitted_counts[thread.thread_id]
            sample = samples[thread.thread_id]
            suffix = f", … (+{count - len(sample)} more)" if count > len(sample) else ""
            warnings.append(
                f"Strict list omits {count} unread Issues from {thread.name[:80]}: "
                + ", ".join(sample)
                + suffix
            )
        if len(affected) > 10:
            warnings.append(f"Partial coverage also affects {len(affected) - 10} more Threads.")
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

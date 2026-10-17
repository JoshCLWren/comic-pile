"""Pure shadow diagnostic: proposed lists never change current Roll decisions."""

from dataclasses import asdict

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.reading_shadow_repository import ShadowReadingInputs, load_shadow_inputs
from app.services.reading_list_cycle_validator import (
    ReadingCycleError,
    validate_reading_constraints,
)
from app.services.reading_list_evaluator import ReadingSnapshot, ThreadEligibility, evaluate


def compare_reading_eligibility(
    inputs: ShadowReadingInputs,
    *,
    max_threads: int = 1000,
    max_blockers: int = 50,
) -> dict[str, object]:
    """Compare stored cache, legacy frontier edges and proposed Option E eligibility.

    The stored-cache pool predicate matches the current queue before dice,
    snoozes and session skips. It deliberately includes shell Threads because
    the current pool can include them. Proposed eligibility requires a concrete
    derived frontier. All counts cover the complete input, even when detail is
    truncated. Invalid or incomplete graphs produce null proposed eligibility,
    never an apparent passing parity result. Raw notes, titles, usernames and
    database credentials are not emitted.

    Args:
        inputs: Detached owner-scoped inputs from one consistent read.
        max_threads: Maximum emitted Thread details, sorted by stable ID.
        max_blockers: Maximum reasons and waiting Issue IDs per emitted Thread.

    Returns:
        Deterministic JSON-compatible diagnostic; never a conversion approval.
    """
    if max_threads < 1 or max_blockers < 1:
        raise ValueError("Report limits must be positive")
    diagnostics: list[dict[str, object]] = [
        {"code": "unresolved_reference", "kind": row.kind, "object_id": row.object_id}
        for row in inputs.unresolved
    ]
    diagnostics.extend(
        {"code": "stranded_prerequisite", "prerequisite_id": row.prerequisite_id}
        for row in inputs.prerequisites
        if row.source_issue_id in inputs.excluded_issue_ids
    )
    snapshot: ReadingSnapshot | None = None
    result: dict[int, ThreadEligibility] | None = None
    try:
        snapshot = ReadingSnapshot(
            inputs.user_id,
            inputs.threads,
            inputs.issues,
            inputs.lists,
            inputs.prerequisites,
            inputs.excluded_issue_ids,
        )
        validate_reading_constraints(snapshot)
        if not diagnostics:
            result = evaluate(snapshot)
    except ReadingCycleError as error:
        diagnostics.append(
            {
                "code": "reading_cycle",
                "path": [
                    {
                        "source_issue_id": edge.source_issue_id,
                        "target_issue_id": edge.target_issue_id,
                        "origin": edge.origin,
                    }
                    for edge in error.edges[:max_blockers]
                ],
                "edge_count": len(error.edges),
                "truncated": len(error.edges) > max_blockers,
            }
        )
    except ValueError:
        # Diagnostic object IDs above identify unresolved evidence. Never echo
        # arbitrary text containing foreign endpoints or historical reader notes.
        diagnostics.append({"code": "invalid_snapshot"})
    by_id = {issue.issue_id: issue for issue in inputs.issues}
    frontiers: dict[int, int] = {}
    for issue in sorted(inputs.issues, key=lambda row: (row.position, row.issue_id)):
        if issue.status != "read" and issue.issue_id not in inputs.excluded_issue_ids:
            frontiers.setdefault(issue.thread_id, issue.issue_id)
    statuses = {thread.thread_id: thread.status for thread in inputs.threads}
    active = {thread.thread_id for thread in inputs.threads if thread.status == "active"}
    unread = {issue.issue_id for issue in inputs.issues if issue.status != "read"}
    targets = {
        row.target_issue_id
        for row in inputs.prerequisites
        if row.source_issue_id in unread and row.target_issue_id in by_id
        and row.prerequisite_id not in inputs.legacy_note_ignored_prerequisite_ids
    }
    rows: list[dict[str, object]] = []
    for stored in sorted(inputs.stored, key=lambda row: row.thread_id):
        frontier = frontiers.get(stored.thread_id)
        current_pool = (
            stored.thread_id in active and stored.queue_position >= 1 and not stored.is_blocked
        )
        legacy_blocked = stored.next_issue_id in targets
        derived_blocked = frontier in targets
        proposed = result.get(stored.thread_id) if result is not None else None
        proposed_eligible = (
            proposed.eligible if proposed is not None else False if result is not None else None
        )
        proposed_pool = (
            proposed_eligible and stored.queue_position >= 1
            if proposed_eligible is not None
            else None
        )
        blockers: list[dict[str, object]] = []
        if proposed is not None:
            for blocker in proposed.blockers[:max_blockers]:
                reason = asdict(blocker)
                reason["waiting_on_issue_ids"] = blocker.waiting_on_issue_ids[:max_blockers]
                reason["waiting_on_count"] = len(blocker.waiting_on_issue_ids)
                reason["waiting_on_truncated"] = len(blocker.waiting_on_issue_ids) > max_blockers
                # The shadow artifact needs identity/origin, not historical prose.
                reason.pop("provenance")
                blockers.append(reason)
        pointed = by_id.get(stored.next_issue_id) if stored.next_issue_id is not None else None
        rows.append(
            {
                "thread_id": stored.thread_id,
                "status": statuses[stored.thread_id],
                "stored_next_issue_id": stored.next_issue_id if pointed is not None else None,
                "stored_pointer_present": stored.next_issue_id is not None,
                "stored_pointer_in_thread": (
                    None
                    if stored.next_issue_id is None
                    else pointed is not None and pointed.thread_id == stored.thread_id
                ),
                "derived_next_issue_id": frontier,
                "frontier_divergence": stored.next_issue_id != frontier,
                "stored_is_blocked": stored.is_blocked,
                "legacy_stored_frontier_blocked": legacy_blocked,
                "legacy_derived_frontier_blocked": derived_blocked,
                "cache_divergence": stored.is_blocked != legacy_blocked,
                "current_pool_candidate": current_pool,
                "proposed_eligible": proposed_eligible,
                "proposed_pool_candidate": proposed_pool,
                "eligibility_divergence": (
                    current_pool != proposed_pool if proposed_pool is not None else None
                ),
                "blockers": blockers,
                "blocker_count": len(proposed.blockers) if proposed is not None else None,
                "blockers_truncated": len(proposed.blockers) > max_blockers
                if proposed is not None
                else False,
            }
        )
    return {
        "schema_version": 1,
        "read_only": True,
        "user_id": inputs.user_id,
        "scope": "proposed authored lists; pre-dice queue candidates; no activation",
        "valid": result is not None,
        "summary": {
            "threads": len(rows),
            "active_threads": len(active),
            "issues": len(inputs.issues),
            "lists": len(inputs.lists),
            "list_entries": sum(len(row.entries) for row in inputs.lists),
            "prerequisites": len(inputs.prerequisites),
            "inert_dependencies": inputs.inert_dependency_count,
            "excluded_issues": len(inputs.excluded_issue_ids),
            "frontier_divergences": sum(row["frontier_divergence"] is True for row in rows),
            "cache_divergences": sum(row["cache_divergence"] is True for row in rows),
            "eligibility_divergences": (
                sum(row["eligibility_divergence"] is True for row in rows)
                if result is not None
                else None
            ),
        },
        "lists": [
            {"list_id": row.list_id, "mode": row.mode, "entry_count": len(row.entries)}
            for row in inputs.lists[:max_threads]
        ],
        "lists_truncated": len(inputs.lists) > max_threads,
        "threads": rows[:max_threads],
        "threads_truncated": len(rows) > max_threads,
        "diagnostics": diagnostics[:max_threads],
        "diagnostic_count": len(diagnostics),
        "diagnostics_truncated": len(diagnostics) > max_threads,
    }


async def shadow_reading_eligibility(
    db: AsyncSession,
    user_id: int,
    *,
    max_threads: int = 1000,
    max_blockers: int = 50,
) -> dict[str, object]:
    """Run the read-only comparison without modifying Roll or any persisted state.

    Args:
        db: Read transaction; use the report CLI for a repeatable-read artifact.
        user_id: Reader whose proposed list decisions should be compared.
        max_threads: Detail limit, independent of aggregate counts.
        max_blockers: Per-Thread reason and waiting-Issue limit.

    Returns:
        Deterministic shadow diagnostic.
    """
    return compare_reading_eligibility(
        await load_shadow_inputs(db, user_id),
        max_threads=max_threads,
        max_blockers=max_blockers,
    )

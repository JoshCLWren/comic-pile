"""Read-only audit of unread issues omitted from participating strict lists."""

from app.services.reading_list_evaluator import ReadingSnapshot


def partial_strict_coverage(snapshot: ReadingSnapshot) -> tuple[tuple[int, int], ...]:
    """Identify unread strict-list Thread issues absent from the list.

    Args:
        snapshot: Complete owner-scoped reading data, including read statuses.

    Returns:
        Ordered pairs of Reading List ID and omitted unread Issue ID.
        Omissions are diagnostic until their scope is checked separately.
    """
    lookup = {issue.issue_id: issue.thread_id for issue in snapshot.issues}
    unread = tuple(
        issue for issue in snapshot.issues
        if issue.status != "read" and issue.issue_id not in snapshot.excluded_issue_ids
    )
    missing = []
    for reading_list in snapshot.lists:
        if reading_list.mode != "strict":
            continue
        included = {e.issue_id for e in reading_list.entries if not e.skipped}
        threads = {lookup[issue_id] for issue_id in included}
        for issue in unread:
            if issue.thread_id in threads and issue.issue_id not in included:
                missing.append((reading_list.list_id, issue.issue_id))
    return tuple(sorted(missing))


def classify_partial_strict_coverage(
    snapshot: ReadingSnapshot,
    omitted: tuple[tuple[int, int], ...],
    plan_memberships: dict[int, frozenset[int]],
) -> tuple[tuple[tuple[int, int, str], ...], tuple[tuple[int, int], ...]]:
    """Distinguish intentional list boundaries from missing included-plan issues.

    An owned Reading List may deliberately include only a subset of a Thread.
    Issues outside its first/last included Issue are out of scope. Within that
    range, omissions are considered scoped only when the list's linked *old*
    Reading Plan also excludes the exact Issue ID. Unknown plan provenance
    remains an unresolved omission rather than a presumed user preference.

    Args:
        snapshot: Current reader-owned Option E graph.
        omitted: Pairs returned by partial_strict_coverage.
        plan_memberships: Linked old-plan Issue IDs keyed by owned list ID,
            using an immutable reading_plan_sources.custom_cbl_list_id link.

    Returns:
        (scoped decisions containing list ID, Issue ID and reason,
        genuinely unresolved list/Issue pairs).
    """
    positions = {issue.issue_id: issue.position for issue in snapshot.issues}
    threads = {issue.issue_id: issue.thread_id for issue in snapshot.issues}
    extents: dict[tuple[int, int], tuple[int, int]] = {}
    for reading_list in snapshot.lists:
        if reading_list.mode != "strict":
            continue
        for entry in reading_list.entries:
            if entry.skipped:
                continue
            tid = threads[entry.issue_id]
            pos = positions[entry.issue_id]
            key = (reading_list.list_id, tid)
            if key in extents:
                low, high = extents[key]
                extents[key] = (min(low, pos), max(high, pos))
            else:
                extents[key] = (pos, pos)
    scoped: list[tuple[int, int, str]] = []
    unresolved: list[tuple[int, int]] = []
    for list_id, issue_id in omitted:
        low, high = extents[(list_id, threads[issue_id])]
        if not low <= positions[issue_id] <= high:
            scoped.append((list_id, issue_id, "outside_list_scope"))
        elif list_id in plan_memberships and issue_id not in plan_memberships[list_id]:
            scoped.append((list_id, issue_id, "also_absent_from_linked_old_plan"))
        else:
            unresolved.append((list_id, issue_id))
    return tuple(scoped), tuple(unresolved)


def superseded_converted_edge(
    source_id: int,
    target_id: int,
    snapshot: ReadingSnapshot,
    plan_positions: dict[int, dict[tuple[int, str], dict[int, int]]],
) -> bool:
    """Identify an old generated pair reversed by an explicitly owned strict list.

    Only applies to an already-diagnosed contradiction whose Dependency has
    generated provenance. The current saved strict Reading List is canonical,
    and the immutable linked older plan must contain both endpoints in the
    opposite order. Unknown and unlinked cases remain unresolved.

    Args:
        source_id: Earlier Issue according to the archived generated edge.
        target_id: Later Issue according to the archived generated edge.
        snapshot: Active owner-owned reading constraints.
        plan_positions: Ordered Issue positions grouped by owned list, then by
            the exact source Reading Plan ID and lane ID. Different source
            plans/lanes must not be merged into a fabricated sequence.

    Returns:
        Whether the archived relation is provably superseded by a current
        strict list containing the same exact Issue IDs.
    """
    for reading_list in snapshot.lists:
        if reading_list.mode != "strict":
            continue
        positions = {
            entry.issue_id: index for index, entry in enumerate(reading_list.entries)
            if not entry.skipped
        }
        if (
            source_id not in positions or target_id not in positions
            or positions[source_id] <= positions[target_id]
        ):
            continue
        # A relation can be superseded only if ONE real older lane contains
        # both ends in the reversed order. Multiple candidate lanes are
        # ambiguous even if one happens to support the claim.
        candidates = [
            old_positions
            for old_positions in plan_positions.get(reading_list.list_id, {}).values()
            if source_id in old_positions and target_id in old_positions
        ]
        if len(candidates) == 1:
            old_positions = candidates[0]
            if old_positions[source_id] < old_positions[target_id]:
                return True
    return False

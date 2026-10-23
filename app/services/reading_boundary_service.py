"""Project canonical Option E eligibility into reader-facing boundary explanations.

The evaluator owns every eligibility decision. This service only turns its
concrete blockers and frontier into named Issues, owned Reading List names,
authored prerequisite origins, and editor targets. Historical or generated
associations are listed separately and never presented as live blockers.
"""

from collections.abc import Collection, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import reading_boundary_repository as boundary_repository
from app.repositories.reading_boundary_repository import (
    BoundaryIssueLabels,
    BoundaryShadowLabels,
)
from app.schemas.reading_boundary import (
    BoundaryEditorTarget,
    BoundaryIssue,
    ReadingBoundaryBatchResponse,
    ReadingBoundaryBlocker,
    ReadingBoundaryExplanation,
    ReadingBoundaryHistorical,
    ReadingBoundaryNext,
)
from app.services.errors import NotFoundError
from app.services.reading_eligibility_service import (
    ReadingEligibilitySnapshot,
    load_eligibility_snapshot,
)
from app.services.reading_list_evaluator import Blocker, ThreadEligibility

_KIND_TEXT = {
    "strict_order": "Strict order",
    "hold": "Hold",
    "after_previous": "Wait for previous",
}
_PREREQUISITE_ORIGIN = {
    "reader": "Reader prerequisite",
    "converted": "Converted prerequisite",
}


def _prerequisite_origin_label(origin: str | None) -> str:
    """Return the reader-facing origin for one prerequisite edge."""
    return _PREREQUISITE_ORIGIN.get(origin or "", "Historical prerequisite")


def _issue_label(labels: BoundaryShadowLabels, issue_id: int) -> BoundaryIssue:
    """Return the reader-facing Issue label for one evaluated Issue.

    Args:
        labels: Owner-scoped label payload loaded for this request.
        issue_id: Evaluated Issue identifier.

    Returns:
        Named Issue, or a stable fallback when a historical row is outside the
        current execution snapshot.
    """
    row: BoundaryIssueLabels | None = labels.issues.get(issue_id)
    if row is None:
        return BoundaryIssue(
            issue_id=issue_id,
            thread_id=0,
            thread_title="Unknown series",
            issue_number="",
            label=f"Issue {issue_id}",
        )
    name = f"{row.thread_title} #{row.issue_number}".strip()
    return BoundaryIssue(
        issue_id=row.issue_id,
        thread_id=row.thread_id,
        thread_title=row.thread_title,
        issue_number=row.issue_number,
        volume_label=row.volume_label,
        label=name,
    )


def _issue_names(labels: BoundaryShadowLabels, issue_ids: Sequence[int]) -> str:
    """Join waiting Issue labels for a stable, readable reason string.

    Args:
        labels: Owner-scoped label payload.
        issue_ids: Waiting Issue identifiers in evaluator order.

    Returns:
        Comma-separated reader-facing Issue names.
    """
    return ", ".join(_issue_label(labels, issue_id).label for issue_id in issue_ids)


def _list_name(
    snapshot: ReadingEligibilitySnapshot,
    labels: BoundaryShadowLabels,
    list_id: int | None,
) -> str:
    """Resolve one owned Reading List name without exposing a storage ID."""
    if list_id is None:
        return "Reading List"
    if list_id in snapshot.list_labels:
        return snapshot.list_labels[list_id]
    row = labels.lists.get(list_id)
    return row.name if row is not None else "Reading List"


def _blocker_editor(
    snapshot: ReadingEligibilitySnapshot,
    labels: BoundaryShadowLabels,
    blocker: Blocker,
) -> BoundaryEditorTarget | None:
    """Return the current owner-scoped editor that governs one blocker."""
    if blocker.list_id is not None:
        return BoundaryEditorTarget(
            kind="reading_list",
            label=_list_name(snapshot, labels, blocker.list_id),
            list_id=blocker.list_id,
        )
    if blocker.prerequisite_id is None:
        return None
    source_id = blocker.waiting_on_issue_ids[0] if blocker.waiting_on_issue_ids else None
    return BoundaryEditorTarget(
        kind="prerequisite",
        label=_prerequisite_origin_label(blocker.origin),
        prerequisite_id=blocker.prerequisite_id,
        issue_id=source_id,
        thread_id=(
            snapshot.issue_thread_ids.get(source_id) if source_id is not None else None
        ),
    )


def _blocker_reason(
    snapshot: ReadingEligibilitySnapshot,
    labels: BoundaryShadowLabels,
    blocker: Blocker,
) -> str:
    """Explain one concrete live blocker with reader-facing names only."""
    waiting = _issue_names(labels, blocker.waiting_on_issue_ids)
    if blocker.kind == "prerequisite":
        origin = _prerequisite_origin_label(blocker.origin)
        return f"{origin}: read {waiting} first"
    list_name = _list_name(snapshot, labels, blocker.list_id)
    kind = _KIND_TEXT[blocker.kind]
    return f"{kind} in {list_name}: read {waiting} first"


def _project_blocker(
    snapshot: ReadingEligibilitySnapshot,
    labels: BoundaryShadowLabels,
    blocker: Blocker,
) -> ReadingBoundaryBlocker:
    """Project one evaluator blocker into the reader response contract."""
    return ReadingBoundaryBlocker(
        kind=blocker.kind,
        origin="reading_list" if blocker.list_id is not None else "reader_prerequisite",
        reason=_blocker_reason(snapshot, labels, blocker),
        waiting_on=[_issue_label(labels, issue_id) for issue_id in blocker.waiting_on_issue_ids],
        editor=_blocker_editor(snapshot, labels, blocker),
    )


def _historical_rows(
    snapshot: ReadingEligibilitySnapshot,
    labels: BoundaryShadowLabels,
    thread_id: int,
) -> list[ReadingBoundaryHistorical]:
    """List owned inactive associations without promoting them to blockers.

    Only the canonical snapshot's explicit prerequisite IDs are active. Every
    other owned Dependency row touching this Thread (unclassified legacy plan
    checkpoints and converted/generated adjacency) stays historical audit data.
    """
    thread_issue_ids = {
        issue_id
        for issue_id, owner_thread_id in snapshot.issue_thread_ids.items()
        if owner_thread_id == thread_id
    }
    rows: list[ReadingBoundaryHistorical] = []
    for prerequisite_id, row in sorted(labels.prerequisites.items()):
        if prerequisite_id in snapshot.active_prerequisite_ids:
            continue
        if (
            row.target_issue_id not in thread_issue_ids
            and row.source_issue_id not in thread_issue_ids
        ):
            continue
        source = _issue_label(labels, row.source_issue_id)
        target = _issue_label(labels, row.target_issue_id)
        converted = row.origin == "converted"
        rows.append(
            ReadingBoundaryHistorical(
                kind="converted_prerequisite" if converted else "legacy_dependency",
                label=f"{source.label} → {target.label}",
                detail=(
                    "Converted generated association; not an active reading requirement."
                    if converted
                    else "Historical association; not an active reading requirement."
                ),
                editor=BoundaryEditorTarget(
                    kind="prerequisite",
                    label=_prerequisite_origin_label(row.origin),
                    prerequisite_id=row.prerequisite_id,
                    issue_id=row.source_issue_id,
                    thread_id=source.thread_id,
                ),
            )
        )
    return rows


def _summary(
    title: str,
    state: ThreadEligibility | None,
    next_issue: BoundaryIssue | None,
    blockers: Sequence[ReadingBoundaryBlocker],
) -> str:
    """Return a concise explanation consistent with the projected state."""
    if state is None:
        return f"{title} is not currently active."
    if next_issue is None:
        return f"{title} has no unread issues."
    if blockers:
        return (
            f"{next_issue.label} is waiting on {len(blockers)} live "
            f"requirement{'s' if len(blockers) != 1 else ''}."
        )
    return f"{next_issue.label} is available next."


def project_boundary_explanation(
    snapshot: ReadingEligibilitySnapshot,
    labels: BoundaryShadowLabels,
    thread_id: int,
) -> ReadingBoundaryExplanation:
    """Project one Thread's canonical evaluator result into an explanation.

    Args:
        snapshot: The same validated Option E result used by Roll and Queue.
        labels: Owner-scoped reader-facing labels.
        thread_id: Owned Thread to explain.

    Returns:
        One explanation whose blockers exactly match the evaluator's blockers.
    """
    thread = labels.threads[thread_id]
    state = snapshot.threads.get(thread_id)
    next_issue = (
        _issue_label(labels, state.next_issue_id)
        if state is not None and state.next_issue_id is not None
        else None
    )
    blockers = (
        [_project_blocker(snapshot, labels, blocker) for blocker in state.blockers]
        if state is not None
        else []
    )
    historical = _historical_rows(snapshot, labels, thread_id)
    if state is None:
        boundary_state = "unavailable"
    elif next_issue is None:
        boundary_state = "complete"
    elif blockers:
        boundary_state = "blocked"
    else:
        boundary_state = "available"
    return ReadingBoundaryExplanation(
        thread_id=thread_id,
        state=boundary_state,
        summary=_summary(thread.title, state, next_issue, blockers),
        next=(
            ReadingBoundaryNext(
                issue=next_issue,
                editor=BoundaryEditorTarget(
                    kind="issue",
                    label=next_issue.label,
                    issue_id=next_issue.issue_id,
                    thread_id=next_issue.thread_id,
                ),
            )
            if next_issue is not None
            else None
        ),
        blockers=blockers,
        historical=historical,
    )


async def get_reading_boundary_explanation(
    db: AsyncSession, *, user_id: int, thread_id: int
) -> ReadingBoundaryExplanation:
    """Explain one owned Thread using the current canonical Option E result.

    Args:
        db: Request transaction.
        user_id: Authenticated reader.
        thread_id: Owned Thread to explain.

    Raises:
        NotFoundError: When the Thread does not exist or belongs to another reader.

    Returns:
        The reader-facing boundary explanation.
    """
    labels = await boundary_repository.load_boundary_labels(db, user_id)
    if thread_id not in labels.threads:
        raise NotFoundError(f"Thread {thread_id} not found")
    snapshot = await load_eligibility_snapshot(db, user_id)
    return project_boundary_explanation(snapshot, labels, thread_id)


async def get_reading_boundary_explanations(
    db: AsyncSession, *, user_id: int, thread_ids: Collection[int]
) -> ReadingBoundaryBatchResponse:
    """Explain several owned Threads from one shared eligibility snapshot.

    Args:
        db: Request transaction.
        user_id: Authenticated reader.
        thread_ids: Owned Thread identifiers to explain.

    Raises:
        NotFoundError: When any requested Thread is absent or foreign.

    Returns:
        Explanations keyed by Thread identifier.
    """
    labels = await boundary_repository.load_boundary_labels(db, user_id)
    missing = [thread_id for thread_id in thread_ids if thread_id not in labels.threads]
    if missing:
        raise NotFoundError(f"Thread {missing[0]} not found")
    snapshot = await load_eligibility_snapshot(db, user_id)
    return ReadingBoundaryBatchResponse(
        threads={
            thread_id: project_boundary_explanation(snapshot, labels, thread_id)
            for thread_id in thread_ids
        }
    )

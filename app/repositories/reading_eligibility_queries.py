"""SQL projections of a validated runtime eligibility result."""

from sqlalchemy import case, literal
from sqlalchemy.sql.elements import ColumnElement

from app.models import Thread
from app.services.reading_eligibility_service import ReadingEligibilitySnapshot


def candidate_predicate(snapshot: ReadingEligibilitySnapshot | None) -> ColumnElement[bool]:
    """Return the selected authority before ordering, weighting or LIMIT.

    Args:
        snapshot: Live reader snapshot, or None for legacy execution.

    Returns:
        Candidate filter for the Thread table.
    """
    if snapshot is None:
        return Thread.is_blocked.is_(False)
    ids = snapshot.candidate_ids()
    # Keep a column expression even for an empty set: PostgreSQL rejects a
    # bare Boolean constant when the complement is used as an ORDER BY key.
    return Thread.id.in_(ids)


def blocked_predicate(snapshot: ReadingEligibilitySnapshot | None) -> ColumnElement[bool]:
    """Return the same authority's blocked or non-offerable Thread predicate.

    Args:
        snapshot: Live reader snapshot, or None for legacy execution.

    Returns:
        Complement of eligible IDs, including empty/excluded active Threads.
    """
    if snapshot is None:
        return Thread.is_blocked.is_(True)
    return ~candidate_predicate(snapshot)


def frontier_expression(snapshot: ReadingEligibilitySnapshot | None) -> ColumnElement[int | None]:
    """Project derived Issue identity without writing a compatibility pointer.

    Args:
        snapshot: Live reader snapshot, or None for legacy execution.

    Returns:
        Per-Thread frontier expression, null when there is no unread candidate.
    """
    if snapshot is None:
        return Thread.next_unread_issue_id.__clause_element__()
    frontiers = {
        thread_id: result.next_issue_id
        for thread_id, result in snapshot.threads.items()
        if result.next_issue_id is not None
    }
    return case(frontiers, value=Thread.id, else_=None) if frontiers else literal(None)

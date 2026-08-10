"""Safely replace one blocked pending roll with a readable prerequisite."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.continuity_chains import resolve_continuity_chains
from app.models import Event, Issue, Session, Thread
from app.roll_recovery import build_roll_recovery
from app.schemas.roll import RollRecoveryInfo
from comic_pile.session import get_current_die, get_or_create


@dataclass(frozen=True, slots=True)
class RollPrerequisiteSwitchResult:
    """Result of replacing a blocked pending roll with one readable issue."""

    original_thread_id: int
    target_thread_id: int
    target_thread_title: str
    target_issue_id: int
    target_issue_number: str
    changed: bool


def _stale_recovery(recovery: RollRecoveryInfo | None) -> HTTPException:
    """Build a conflict response that tells the client to refresh guidance."""
    detail: dict[str, object] = {
        "code": "stale_roll_recovery",
        "message": "The blocked-roll guidance changed. Refresh and choose a current prerequisite.",
    }
    if recovery is not None:
        detail["roll_recovery"] = recovery.model_dump()
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


async def switch_pending_roll_to_prerequisite(
    db: AsyncSession,
    *,
    user_id: int,
    node_type: Literal["issue", "crossover"],
    node_id: int,
) -> RollPrerequisiteSwitchResult:
    """Switch the current blocked roll to a still-readable prerequisite.

    The mutation never changes issue read/rating state. It preserves the original
    roll event for audit, appends a new roll event with
    ``selection_method=dependency_recovery``, and points the session at the
    prerequisite's owning thread. Repeated requests for the already-active
    prerequisite return success without creating another event.

    Args:
        db: Async database session.
        user_id: Authenticated owner of the reading session.
        node_type: Recommended continuity-node type selected by the reader.
        node_id: Recommended continuity-node identifier.

    Returns:
        The active prerequisite target and whether durable state changed.

    Raises:
        HTTPException: When there is no pending roll, the recommendation is
            stale, or the selected node cannot safely become a Roll target.
    """
    if node_type != "issue":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "unsupported_roll_prerequisite",
                "message": "Choose a concrete readable issue before switching the Roll target.",
            },
        )

    issue_result = await db.execute(
        select(Issue, Thread)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Issue.id == node_id)
        .where(Thread.user_id == user_id)
    )
    target_row = issue_result.one_or_none()
    if target_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Issue {node_id} not found",
        )
    target_issue, target_thread = target_row

    current_session = await get_or_create(db, user_id=user_id)
    session_result = await db.execute(
        select(Session)
        .where(Session.id == current_session.id)
        .where(Session.user_id == user_id)
        .with_for_update()
    )
    locked_session = session_result.scalar_one()

    if locked_session.pending_thread_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "no_pending_roll", "message": "There is no pending roll to recover."},
        )

    original_thread_id = locked_session.pending_thread_id
    original_thread_result = await db.execute(
        select(Thread.title)
        .where(Thread.id == original_thread_id)
        .where(Thread.user_id == user_id)
    )
    original_title = original_thread_result.scalar_one_or_none()

    if (
        target_issue.status != "unread"
        or target_thread.next_unread_issue_id != target_issue.id
        or target_thread.status != "active"
    ):
        refreshed = await build_roll_recovery(
            db,
            user_id=user_id,
            pending_thread_id=original_thread_id,
            pending_thread_title=original_title,
        )
        raise _stale_recovery(refreshed)

    target_readiness = await resolve_continuity_chains(
        db,
        user_id=user_id,
        node_type="issue",
        node_id=target_issue.id,
    )
    if target_readiness.direct_blockers:
        refreshed = await build_roll_recovery(
            db,
            user_id=user_id,
            pending_thread_id=original_thread_id,
            pending_thread_title=original_title,
        )
        raise _stale_recovery(refreshed)

    # Duplicate taps after a successful switch are idempotent, but only while
    # the target is still the same readable next issue.
    if locked_session.pending_thread_id == target_thread.id:
        return RollPrerequisiteSwitchResult(
            original_thread_id=original_thread_id,
            target_thread_id=target_thread.id,
            target_thread_title=target_thread.title,
            target_issue_id=target_issue.id,
            target_issue_number=target_issue.issue_number,
            changed=False,
        )

    recovery = await build_roll_recovery(
        db,
        user_id=user_id,
        pending_thread_id=original_thread_id,
        pending_thread_title=original_title,
    )
    if recovery is None:
        raise _stale_recovery(None)

    allowed = {
        (prerequisite.node_type, prerequisite.node_id)
        for prerequisite in recovery.readable_prerequisites
    }
    if (node_type, node_id) not in allowed:
        raise _stale_recovery(recovery)

    snoozed_ids = list(locked_session.snoozed_thread_ids or [])
    if target_thread.id in snoozed_ids:
        locked_session.snoozed_thread_ids = [
            thread_id for thread_id in snoozed_ids if thread_id != target_thread.id
        ]

    target_thread_id = target_thread.id
    target_thread_title = target_thread.title
    target_issue_id = target_issue.id
    target_issue_number = target_issue.issue_number
    current_die = await get_current_die(locked_session.id, db)
    db.add(
        Event(
            type="roll",
            session_id=locked_session.id,
            selected_thread_id=target_thread_id,
            issue_id=target_issue_id,
            issue_number=target_issue_number,
            die=current_die,
            result=0,
            selection_method="dependency_recovery",
        )
    )
    locked_session.pending_thread_id = target_thread_id
    locked_session.pending_thread_updated_at = datetime.now(UTC)
    await db.commit()

    return RollPrerequisiteSwitchResult(
        original_thread_id=original_thread_id,
        target_thread_id=target_thread_id,
        target_thread_title=target_thread_title,
        target_issue_id=target_issue_id,
        target_issue_number=target_issue_number,
        changed=True,
    )

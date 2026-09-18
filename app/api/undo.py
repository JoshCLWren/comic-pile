"""Undo API endpoints."""

from typing import Annotated

import asyncio

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.cache_invalidation import invalidate_user_view
from app.database import get_db
from app.models import Session as SessionModel
from app.models.user import User
from app.schemas import SessionResponse
from app.schemas.session import build_session_intent_state
from app.services.undo_snapshot_service import UndoSnapshotService

router = APIRouter(tags=["undo"])


@router.post("/{session_id}/undo/{snapshot_id}")
async def undo_to_snapshot(
    session_id: int,
    snapshot_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    """Undo session state to a snapshot.

    Args:
        session_id: Session to restore.
        snapshot_id: Snapshot to restore.
        current_user: Authenticated user.
        db: Database session.

    Returns:
        Restored session response.

    Raises:
        HTTPException: If the session or snapshot is not found.
        RuntimeError: If all deadlock retries fail.
    """
    max_retries = 3
    initial_delay = 0.1
    retries = 0

    while retries < max_retries:
        try:
            # Use service to apply snapshot
            service = UndoSnapshotService(db)
            session, response_values, snapshot_info = await service.apply_snapshot(
                session_id, snapshot_id, current_user.id
            )

            await db.commit()

            await invalidate_user_view(current_user.id)

            # Build response from pre-computed values (safe: extracted before commit)
            return SessionResponse(
                id=session_id,
                started_at=session.started_at,
                ended_at=session.ended_at,
                start_die=session.start_die,
                manual_die=session.manual_die,
                user_id=session.user_id,
                ladder_path=response_values["ladder_path"],
                active_thread=response_values["active_info"],
                current_die=response_values["current_die"],
                last_rolled_result=response_values["active_event"].result if response_values["active_event"] else None,
                has_restore_point=response_values["snapshot_count"] > 0,
                snapshot_count=response_values["snapshot_count"],
                pending_thread_id=session.pending_thread_id,
                timezone=session.timezone,
                intent=build_session_intent_state(
                    predicted_intent=session.predicted_intent,
                    active_intent=session.active_intent,
                    confidence=session.intent_confidence,
                    source=session.intent_source,
                    mode_version=session.intent_version,
                ),
            )
        except OperationalError as error:
            if "deadlock" not in str(error).lower():
                raise
            await db.rollback()
            retries += 1
            if retries >= max_retries:
                raise
            await asyncio.sleep(initial_delay * (2 ** (retries - 1)))

    raise RuntimeError(f"Failed to undo to snapshot after {max_retries} retries")


@router.get("/{session_id}/snapshots")
async def list_session_snapshots(
    session_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List all snapshots for a session.

    Args:
        session_id: Session whose snapshots should be listed.
        current_user: Authenticated user.
        db: Database session.

    Returns:
        Snapshot metadata in reverse chronological order.

    Raises:
        HTTPException: If the session is not owned by the current user.
    """
    # Verify session ownership
    session = await db.get(SessionModel, session_id)
    if not session or session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )

    # Use service to list snapshots
    service = UndoSnapshotService(db)
    return await service.list_session_snapshots(session_id, current_user.id)

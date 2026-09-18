"""Undo API endpoints."""

from typing import Annotated

import asyncio

from fastapi import APIRouter, Depends
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.cache_invalidation import invalidate_user_view
from app.database import get_db
from app.models.user import User
from app.schemas import SessionResponse, SnapshotResponse, SnapshotsListResponse
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

            # Extract every ORM attribute BEFORE commit: post-commit access
            # would trigger a lazy load on the expired session (MissingGreenlet).
            started_at = session.started_at
            ended_at = session.ended_at
            start_die = session.start_die
            manual_die = session.manual_die
            owner_id = session.user_id
            pending_thread_id = session.pending_thread_id
            timezone = session.timezone
            predicted_intent = session.predicted_intent
            active_intent = session.active_intent
            intent_confidence = session.intent_confidence
            intent_source = session.intent_source
            intent_version = session.intent_version

            await db.commit()

            await invalidate_user_view(current_user.id)

            # Build response from pre-computed values (safe: extracted before commit)
            return SessionResponse(
                id=session_id,
                started_at=started_at,
                ended_at=ended_at,
                start_die=start_die,
                manual_die=manual_die,
                user_id=owner_id,
                ladder_path=response_values["ladder_path"],
                active_thread=response_values["active_info"],
                current_die=response_values["current_die"],
                last_rolled_result=response_values["last_rolled_result"],
                has_restore_point=response_values["snapshot_count"] > 0,
                snapshot_count=response_values["snapshot_count"],
                pending_thread_id=pending_thread_id,
                timezone=timezone,
                intent=build_session_intent_state(
                    predicted_intent=predicted_intent,
                    active_intent=active_intent,
                    confidence=intent_confidence,
                    source=intent_source,
                    mode_version=intent_version,
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
) -> SnapshotsListResponse:
    """List all snapshots for a session.

    Args:
        session_id: Session whose snapshots should be listed.
        current_user: Authenticated user.
        db: Database session.

    Returns:
        Typed snapshot list in reverse chronological order.

    Raises:
        HTTPException: If the session is not owned by the current user.
    """
    # Service verifies session ownership and loads snapshots
    service = UndoSnapshotService(db)
    snapshots = await service.list_session_snapshots(session_id, current_user.id)
    return SnapshotsListResponse(
        session_id=session_id,
        snapshots=[
            SnapshotResponse(
                id=snapshot.id,
                session_id=snapshot.session_id,
                created_at=snapshot.created_at,
                description=snapshot.description,
                event_id=snapshot.event_id,
            )
            for snapshot in snapshots
        ],
    )

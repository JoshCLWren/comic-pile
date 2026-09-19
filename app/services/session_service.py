"""Session business logic coordination.

This service orchestrates session-related operations, coordinating between
the session and thread repositories.
"""


import asyncio

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import OperationalError

from app.database import get_db
from app.models import Session as SessionModel
from app.repositories import session_repository
from app.services.ownership import get_owned_session_or_404
from app.services.thread_issue_stats import load_unread_counts
from comic_pile.dependencies import refresh_user_blocked_status


class SessionService:
    """Service for handling session business logic."""

    def __init__(self, db: AsyncSession):
        """Initialize the SessionService with a database session.

        Args:
            db: SQLAlchemy async session.
        """
        self.db = db

    async def restore_session_start(self, session_id: int, user_id: int) -> SessionModel:
        """Restore session to its initial state at session start.

        Args:
            session_id: The session ID to restore.
            user_id: The user ID for ownership validation.

        Returns:
            The restored session model.

        Raises:
            HTTPException: If session or snapshot not found.
            RuntimeError: If failed after max retries due to deadlocks.
        """
        max_retries = 3
        initial_delay = 0.1
        retries = 0

        while retries < max_retries:
            try:
                session = await get_owned_session_or_404(self.db, user_id, session_id)

                snapshot = await session_repository.first_start_snapshot(self.db, session_id)
                if not snapshot:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"No session start snapshot found for session {session_id}",
                    )

                # Use repository to perform the data restoration
                session, affected_threads = await session_repository.restore_session_start(
                    self.db, session, snapshot, user_id
                )

                # Recount issues for affected threads that use issue tracking
                threads_to_recount = [t for t in affected_threads if t.uses_issue_tracking()]
                if threads_to_recount:
                    await self.db.flush()
                    unread_counts = await load_unread_counts(threads_to_recount, self.db)
                    for thread_obj in threads_to_recount:
                        thread_obj.issues_remaining = unread_counts.get(thread_obj.id, 0)

                await self.db.commit()
                await self.db.refresh(session)

                # Sync user status
                await refresh_user_blocked_status(user_id, self.db)
                await self.db.commit()
                await self.db.refresh(session)

                return session

            except OperationalError as e:
                if "deadlock" in str(e).lower():
                    await self.db.rollback()
                    retries += 1
                    if retries >= max_retries:
                        raise
                    await asyncio.sleep(initial_delay * (2 ** (retries - 1)))
                else:
                    raise

        raise RuntimeError(f"Failed to restore session after {max_retries} retries")


async def get_session_service(db: AsyncSession = Depends(get_db)) -> SessionService:
    """Dependency provider for SessionService."""
    return SessionService(db)

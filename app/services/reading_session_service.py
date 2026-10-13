"""ReadingSession business logic coordination.

This service orchestrates reading-history operations (restore-to-start, active
reading-session resolution), coordinating between the reading-session and thread
repositories. It is not an authentication/login-session service.
"""


import asyncio

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import OperationalError

from app.database import get_db
from app.models import ReadingSession, Thread, Issue
from app.repositories import reading_session_repository, thread_repository, issue_repository
from app.services.ownership import get_owned_session_or_404
from app.services.thread_issue_stats import load_unread_counts
from app.services.errors import InvalidRequestError
from comic_pile.dependencies import refresh_user_blocked_status


class ReadingSessionService:
    """Service for handling reading-history session business logic."""

    def __init__(self, db: AsyncSession):
        """Initialize the ReadingSessionService with a database session.

        Args:
            db: SQLAlchemy async session.
        """
        self.db = db

    async def _validate_pending_thread_ownership(
        self, session: ReadingSession, user_id: int
    ) -> None:
        """Validate that pending_thread_id belongs to the session user.

        Args:
            session: The reading session to validate.
            user_id: The user ID for ownership validation.

        Raises:
            InvalidRequestError: When pending_thread_id is set and doesn't belong to user.
        """
        if session.pending_thread_id is not None:
            thread = await thread_repository.find_owned(self.db, user_id, session.pending_thread_id)
            if thread is None:
                raise InvalidRequestError(
                    f"Pending thread {session.pending_thread_id} does not exist or "
                    "does not belong to user {user_id}"
                )

    async def _validate_pending_issue_ownership(
        self, session: ReadingSession, user_id: int
    ) -> None:
        """Validate that pending_issue_id belongs to the session user.

        Args:
            session: The reading session to validate.
            user_id: The user ID for ownership validation.

        Raises:
            InvalidRequestError: When pending_issue_id is set and doesn't belong to user.
        """
        if session.pending_issue_id is not None:
            issue = await issue_repository.get_issue(self.db, session.pending_issue_id)
            if issue is None:
                raise InvalidRequestError(
                    f"Pending issue {session.pending_issue_id} does not exist"
                )
            
            # Validate that the issue belongs to a thread owned by the user
            thread = await thread_repository.find_owned(self.db, user_id, issue.thread_id)
            if thread is None:
                raise InvalidRequestError(
                    f"Pending issue {session.pending_issue_id} does not belong to "
                    f"any thread owned by user {user_id}"
                )

    async def restore_reading_session_start(self, session_id: int, user_id: int) -> ReadingSession:
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

                # Validate pending references belong to session user
                await self._validate_pending_thread_ownership(session, user_id)
                await self._validate_pending_issue_ownership(session, user_id)

                snapshot = await reading_session_repository.first_start_snapshot(
                    self.db, session_id
                )
                if not snapshot:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"No session start snapshot found for session {session_id}",
                    )

                # Use repository to perform the data restoration
                session, affected_threads = (
                    await reading_session_repository.restore_reading_session_start(
                        self.db, session, snapshot, user_id
                    )
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


async def get_reading_session_service(
    db: AsyncSession = Depends(get_db),
) -> ReadingSessionService:
    """Dependency provider for ReadingSessionService."""
    return ReadingSessionService(db)

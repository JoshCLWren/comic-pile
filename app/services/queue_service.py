"""Queue move/shuffle orchestration.

Services own business rules, transaction boundaries, reorder-event writes,
and cache invalidation. Persistence (position maps, event rows, and the
queue mutation SQL) lives in ``app/repositories/queue_repository.py`` and
``comic_pile.queue``. HTTP status mapping lives in routers.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.cache_invalidation import invalidate_user_view
from app.repositories import queue_repository, thread_repository
from app.services.errors import InvalidRequestError, NotFoundError
from app.services.thread_service import thread_to_response
from app.schemas import ThreadResponse
from comic_pile.queue import (
    move_to_back as _move_to_back,
    move_to_front as _move_to_front,
    move_to_position as _move_to_position,
    shuffle_queue as _shuffle_queue,
)

logger = logging.getLogger(__name__)


async def invalidate_queue_caches(user_id: int) -> None:
    """Invalidate every cached view affected by queue reordering.

    Args:
        user_id: Owner of the reordered queue.
    """
    await invalidate_user_view(user_id)


class QueueService:
    """Queue list/mutation orchestration for the queue API.

    Owns the move-to-position, move-to-front, move-to-back, and shuffle flows
    previously embedded in ``app.api.queue``, including ownership checks,
    reorder-event persistence, and cache invalidation.
    """

    def __init__(self, db: AsyncSession) -> None:
        """Initialize the service with a database session.

        Args:
            db: Async database session.
        """
        self._db = db

    async def move_to_position(self, user_id: int, thread_id: int, new_position: int) -> ThreadResponse:
        """Move an owned thread to a normalized sequential queue position.

        Args:
            user_id: Owner that must own the thread.
            thread_id: Thread to move.
            new_position: Target sequential position (1-indexed).

        Returns:
            ThreadResponse with the updated thread information.

        Raises:
            NotFoundError: When the thread does not exist for this user.
            InvalidRequestError: When the target position is out of range.
        """
        return await self._move_thread(
            user_id,
            thread_id,
            action="position",
            new_position=new_position,
        )

    async def move_to_front(self, user_id: int, thread_id: int) -> ThreadResponse:
        """Move an owned thread to the front of the queue.

        Args:
            user_id: Owner that must own the thread.
            thread_id: Thread to move.

        Returns:
            ThreadResponse with the updated thread information.

        Raises:
            NotFoundError: When the thread does not exist for this user.
        """
        return await self._move_thread(user_id, thread_id, action="front")

    async def move_to_back(self, user_id: int, thread_id: int) -> ThreadResponse:
        """Move an owned thread to the back of the queue.

        Args:
            user_id: Owner that must own the thread.
            thread_id: Thread to move.

        Returns:
            ThreadResponse with the updated thread information.

        Raises:
            NotFoundError: When the thread does not exist for this user.
        """
        return await self._move_thread(user_id, thread_id, action="back")

    async def _move_thread(
        self,
        user_id: int,
        thread_id: int,
        *,
        action: str,
        new_position: int | None = None,
    ) -> ThreadResponse:
        """Run one queue-mutation flow and record a reorder event on change.

        Args:
            user_id: Owner that must own the thread.
            thread_id: Thread to move.
            action: Mutation kind: ``"position"``, ``"front"``, or ``"back"``.
            new_position: Target position for the ``"position"`` action.

        Returns:
            ThreadResponse with the updated thread information.

        Raises:
            NotFoundError: When the thread does not exist for this user.
            InvalidRequestError: When the target position is out of range.
        """
        thread = await thread_repository.find_owned(self._db, user_id, thread_id)
        if thread is None:
            logger.error("Thread %d not found for user %d", thread_id, user_id)
            raise NotFoundError(f"Thread {thread_id} not found")

        if action == "position":
            if new_position is None:
                raise InvalidRequestError("new_position is required")
            if thread.queue_position == new_position:
                return await thread_to_response(thread, self._db)

        before_positions = await queue_repository.active_queue_positions(self._db, user_id)

        try:
            if action == "position":
                await _move_to_position(thread_id, user_id, new_position, self._db)
            elif action == "front":
                await _move_to_front(thread_id, user_id, self._db)
            else:
                await _move_to_back(thread_id, user_id, self._db)
        except ValueError as exc:
            logger.error(
                "Invalid position %s for thread %s: %s",
                new_position,
                thread_id,
                exc,
            )
            raise InvalidRequestError(str(exc)) from exc

        await self._db.refresh(thread)
        after_positions = await queue_repository.active_queue_positions(self._db, user_id)

        if after_positions != before_positions:
            await queue_repository.add_reorder_event(self._db, thread_id)
            await self._db.commit()
            await self._db.refresh(thread)
            await invalidate_queue_caches(user_id)

        return await thread_to_response(thread, self._db)

    async def shuffle(self, user_id: int) -> None:
        """Randomize all active queue positions for the authenticated user.

        Args:
            user_id: Owner of the queue to shuffle.
        """
        logger.info("Shuffling queue for user %d", user_id)

        before_positions = await queue_repository.active_queue_positions(self._db, user_id)
        await _shuffle_queue(user_id, self._db)
        after_positions = await queue_repository.active_queue_positions(self._db, user_id)
        if after_positions != before_positions:
            await invalidate_queue_caches(user_id)
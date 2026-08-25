"""Reading-mode persistence service.

This service encapsulates all database operations for reading-mode state,
keeping the router layer thin and focused on HTTP concerns.
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache_invalidation import invalidate_user_view
from app.database import get_db
from app.models import Session as SessionModel
from app.models.user import User
from app.services.reading_quiz import (
    QuizResolutionError,
    ReadingModeSource,
    is_valid_reading_mode,
    resolve_quiz_answers,
)


class ReadingModeService:
    """Service for managing session reading-mode state."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_active_session(self, user: User) -> SessionModel:
        """Return the active session for the current user, creating one if needed."""
        from comic_pile.session import get_or_create

        return await get_or_create(self.db, user_id=user.id, existing_user=user)

    async def get_reading_mode(self, user: User) -> dict:
        """Return the active session's current reading mode."""
        session = await self._get_active_session(user)
        return {
            "bandwidth": session.reading_bandwidth,
            "intent": session.reading_intent,
            "source": session.reading_mode_source,
            "suggested": session.reading_mode_suggested,
        }

    async def set_reading_mode(
        self,
        user: User,
        *,
        bandwidth: str | None = None,
        intent: str | None = None,
        answers: dict[str, str] | None = None,
        source: str,
    ) -> dict:
        """Set the active session reading mode.

        Args:
            user: The authenticated user.
            bandwidth: Resolved bandwidth value (manual entry).
            intent: Resolved intent value (manual entry).
            answers: Raw quiz answers keyed by question ID.
            source: Origin of the setting: 'quiz' or 'manual'.

        Returns:
            The newly stored reading-mode state.

        Raises:
            QuizResolutionError: If the answers cannot be resolved.
            ValueError: If neither answers nor both bandwidth/intent are present,
                or if the source is invalid, or if the resolved values are invalid.
        """
        if source not in ReadingModeSource.values():
            raise ValueError(f"Invalid reading-mode source: {source!r}")

        if answers:
            mode = resolve_quiz_answers(answers)
            bandwidth, intent = mode.bandwidth, mode.intent
        elif bandwidth and intent:
            pass  # Use provided values
        else:
            raise ValueError("Provide either quiz answers or both bandwidth and intent")

        if not is_valid_reading_mode(bandwidth, intent):
            raise ValueError(f"Invalid reading-mode values: {bandwidth!r}/{intent!r}")

        session = await self._get_active_session(user)
        session.reading_bandwidth = bandwidth
        session.reading_intent = intent
        session.reading_mode_source = source
        session.reading_mode_suggested = False

        await self.db.commit()
        await self.db.refresh(session)
        await invalidate_user_view(user.id)

        return {
            "bandwidth": session.reading_bandwidth,
            "intent": session.reading_intent,
            "source": session.reading_mode_source,
            "suggested": session.reading_mode_suggested,
        }

    async def dismiss_suggestion(self, user: User) -> dict:
        """Dismiss the reading-mode suggestion without changing the current mode."""
        session = await self._get_active_session(user)
        session.reading_mode_suggested = False

        await self.db.commit()
        await self.db.refresh(session)
        await invalidate_user_view(user.id)

        return {
            "bandwidth": session.reading_bandwidth,
            "intent": session.reading_intent,
            "source": session.reading_mode_source,
            "suggested": session.reading_mode_suggested,
        }

    async def suggest_reading_mode(self, user: User) -> dict:
        """Mark the active session as a candidate for the reading-mode quiz."""
        session = await self._get_active_session(user)
        session.reading_mode_suggested = True

        await self.db.commit()
        await self.db.refresh(session)
        await invalidate_user_view(user.id)

        return {
            "bandwidth": session.reading_bandwidth,
            "intent": session.reading_intent,
            "source": session.reading_mode_source,
            "suggested": session.reading_mode_suggested,
        }


def get_reading_mode_service(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReadingModeService:
    """FastAPI dependency for ReadingModeService."""
    return ReadingModeService(db)
"""Shared in-process Roll flow for Python tests after the v1 retirement (#4336).

``POST /api/v1/roll/`` and its unversioned ``/api/roll/`` alias were retired in
#4336. The public Roll mutation is now the sessionless native
``POST /api/v2/roll/offer``, which is not served by the Python FastAPI app.

Python tests still need a real pending Roll to drive the retained Python
behavior they cover (skip, dismiss, snooze, rating, event history). This module
runs that flow directly against the test database through the same
``RollService`` methods the live skip route uses, so no selection, eligibility,
weighting, event-history, or pending-state rule is reimplemented here.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas import RollResponse
from app.services.roll_service import RollService
from comic_pile.reading_session import get_or_create


async def roll_pending_thread(
    db: AsyncSession,
    *,
    user: User | None = None,
    bandwidth: str | None = None,
    intent: str | None = None,
) -> RollResponse:
    """Select a thread for the reader's session and leave it pending.

    Args:
        db: Test database session shared with the authenticated API client.
        user: Owner to roll for; defaults to the authenticated test user.
        bandwidth: Optional explicit reading-bandwidth override.
        intent: Optional explicit reading-intent override.

    Returns:
        The persisted ``RollResponse`` for the newly pending thread.

    Raises:
        HTTPException: 400 when the reader has no eligible thread to roll.
    """
    if user is None:
        from tests.conftest import get_or_create_user_async

        user = await get_or_create_user_async(db)

    service = RollService(db)
    current_session = await get_or_create(
        db,
        user_id=user.id,
        existing_user=user,
    )
    current_die, artifacts = await service.prepare_selection(
        current_session=current_session,
        user_id=user.id,
        bandwidth=bandwidth,
        intent=intent,
    )
    return await service.persist_selection(
        current_session=current_session,
        artifacts=artifacts,
        current_die=current_die,
    )

"""Retired Reviews API surface.

The frontend no longer exposes Reviews. Keep an empty router temporarily so the
application wiring can be removed independently while former endpoints fall
through to the standard JSON 404 handler.

The response serializer remains temporarily because the legacy thread-scoped
reviews endpoint still imports it. That endpoint and this compatibility helper
must be deleted together in the next removal step.
"""

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Review
from app.schemas.review import ReviewResponse

router = APIRouter(tags=["reviews"])


async def _create_or_update_review_response(
    review: Review,
    db: AsyncSession,
) -> ReviewResponse:
    """Serialize a review for the temporary thread-scoped compatibility route.

    Args:
        review: Review with thread and issue relationships already loaded.
        db: Database session retained for compatibility with the existing caller.

    Returns:
        Serialized review response.
    """
    del db
    return ReviewResponse(
        id=review.id,
        user_id=review.user_id,
        thread_id=review.thread_id,
        rating=review.rating,
        review_text=review.review_text,
        issue_id=review.issue_id,
        issue_number=review.issue.issue_number if review.issue else None,
        thread_title=review.thread.title,
        thread_format=review.thread.format,
        created_at=review.created_at,
        updated_at=review.updated_at,
    )

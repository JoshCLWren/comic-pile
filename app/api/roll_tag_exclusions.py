"""Roll tag-exclusion API routes (issue #3033).

Thin routing layer: authentication, request/response schema validation, HTTP
status mapping, and exactly one service call per endpoint. Business logic
lives in ``app.services``; persistence lives in ``app.repositories``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import Tag
from app.models.user import User
from app.schemas import roll as roll_schemas
from app.schemas.tags import TagResponse
from app.services.errors import NotFoundError
from app.services.roll_service import RollService
from app.services.roll_tag_exclusion_service import RollTagExclusionService

router = APIRouter(tags=["roll"])


def _tag_to_response(tag: Tag) -> TagResponse:
    """Convert an ORM tag to its API response model."""
    return TagResponse(
        id=tag.id,
        name=tag.name,
        normalized_name=tag.normalized_name,
        scope=tag.scope,
        owner_user_id=tag.owner_user_id,
        color=tag.color,
        created_at=tag.created_at,
        updated_at=tag.updated_at,
    )


async def _list_response(    service: RollTagExclusionService, user: User
) -> roll_schemas.TagExclusionListResponse:
    """Build the exclusion-list response for one user."""
    tags = await service.list_excluded_tags(user)
    return roll_schemas.TagExclusionListResponse(
        excluded_tags=[_tag_to_response(tag) for tag in tags]
    )


@router.get("/", response_model=roll_schemas.TagExclusionListResponse)
async def list_tag_exclusions(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> roll_schemas.TagExclusionListResponse:
    """Return the user's active account-wide Roll tag exclusions.

    Args:
        current_user: The authenticated user.
        db: Database session.

    Returns:
        The active excluded tags.
    """
    service = RollTagExclusionService(db)
    return await _list_response(service, current_user)


@router.post("/", response_model=TagResponse)
async def add_tag_exclusion(
    request: roll_schemas.TagExclusionAddRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TagResponse:
    """Persist an account-wide Roll tag exclusion.

    The operation is idempotent: excluding an already-excluded tag returns the
    tag unchanged. Persisting an exclusion has no snooze, backoff, bandwidth,
    rating, or recommendation side effects, and does not disturb a pending
    roll. Use the exclude-and-reroll action for the mid-roll flow that
    replaces an invalidated pending result.

    Args:
        request: The exclusion request carrying the tag ID.
        current_user: The authenticated user.
        db: Database session.

    Returns:
        The excluded tag.

    Raises:
        HTTPException 404: When the tag does not exist or is not visible to
            the user.
    """
    service = RollTagExclusionService(db)
    try:
        tag = await service.add_exclusion(current_user, request.tag_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _tag_to_response(tag)


@router.delete("/{tag_id}/", response_model=TagResponse)
async def remove_tag_exclusion(
    tag_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TagResponse:
    """Remove an account-wide Roll tag exclusion.

    Removing an exclusion makes matching candidates eligible immediately.

    Args:
        tag_id: Tag to stop excluding.
        current_user: The authenticated user.
        db: Database session.

    Returns:
        The formerly excluded tag.

    Raises:
        HTTPException 404: When the tag does not exist, is not visible to the
            user, or is not currently excluded by the user.
    """
    service = RollTagExclusionService(db)
    try:
        tag = await service.remove_exclusion(current_user, tag_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _tag_to_response(tag)


@router.post(
    "/{tag_id}/exclude-and-reroll/",
    response_model=roll_schemas.ExcludeTagAndRerollResponse,
)
async def exclude_tag_and_reroll(
    tag_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> roll_schemas.ExcludeTagAndRerollResponse:
    """Exclude a tag mid-roll, replacing an invalidated pending result.

    Persists the account-wide exclusion, then checks the currently pending
    issue's effective tags: when the pending result became ineligible it is
    cleared and another eligible result is selected through normal Roll
    selection. The action is never recorded as a snooze or negative
    preference signal. When no pending roll exists, or the pending result
    stays eligible, only the exclusion is persisted.

    Args:
        tag_id: Tag to exclude from Roll eligibility.
        current_user: The authenticated user.
        db: Database session.

    Returns:
        The exclusion outcome with the replacement roll when the pending
        result was invalidated.

    Raises:
        HTTPException 404: When the tag does not exist or is not visible to
            the user.
        HTTPException 400: When the exclusion empties the eligible pool; the
            detail names the responsible exclusions.
    """
    service = RollService(db)
    result = await service.execute_exclude_tag_and_reroll(
        user=current_user, tag_id=tag_id
    )
    return roll_schemas.ExcludeTagAndRerollResponse(
        excluded_tag=_tag_to_response(result.excluded_tag),
        pending_invalidated=result.pending_invalidated,
        roll=result.roll,
    )

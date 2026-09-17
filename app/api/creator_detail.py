"""Bounded personal creator detail API (issue #2037).

Endpoints:

- ``GET /api/v1/creators/{creator_key}`` — detailed personal creator information
  including ratings, upcoming issues, and role breakdown.

This router validates requests and delegates aggregation to the creator detail
service. It performs no query construction and no direct persistence.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.creator_detail import CreatorDetailResponse
from app.services.creator_detail import get_creator_detail, parse_creator_key

router = APIRouter(prefix="/api/v1/creators", tags=["creators"])


@router.get(
    "/{creator_key}",
    response_model=CreatorDetailResponse,
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "Creator not found in user's library or invalid key format"
        },
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Authentication required"
        },
    },
)
async def get_creator_detail_endpoint(
    current_user: Annotated[User, Depends(get_current_user)],
    creator_key: Annotated[str, Path(description="Canonical creator key (e.g., creator:12345)")],
    db: AsyncSession = Depends(get_db),
    page_token: str | None = Query(default=None, description="Token for pagination"),
    page_size: int = Query(default=20, ge=1, le=100, description="Number of items per page"),
) -> CreatorDetailResponse:
    """Return detailed personal information for the requested creator key.

    Only creator keys visible in the authenticated user's own confirmed issue
    metadata are returned; unknown or foreign keys result in a 404 response.

    Args:
        current_user: Authenticated user whose library is accessed.
        creator_key: Canonical creator key to retrieve details for.
        db: Async database session.
        page_token: Token for pagination (optional).
        page_size: Maximum number of items per page (1-100, default 20).

    Returns:
        Detailed creator information including ratings, upcoming issues, and role breakdown.

    Raises:
        HTTPException: When the creator key is invalid or not found in the user's library.
    """
    try:
        return await get_creator_detail(
            db, current_user.id, creator_key, page_token, page_size
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )


@router.get(
    "/{creator_key}/exists",
    response_model=dict[str, bool],
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "Creator not found in user's library or invalid key format"
        },
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Authentication required"
        },
    },
)
async def check_creator_exists(
    current_user: Annotated[User, Depends(get_current_user)],
    creator_key: Annotated[str, Path(description="Canonical creator key (e.g., creator:12345)")],
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    """Check if a creator exists in the user's library.

    This is a lightweight endpoint for frontend navigation validation.

    Args:
        current_user: Authenticated user whose library is checked.
        creator_key: Canonical creator key to check.
        db: Async database session.

    Returns:
        Dictionary with 'exists' boolean indicating if the creator is in the user's library.

    Raises:
        HTTPException: When the creator key format is invalid.
    """
    creator_id = parse_creator_key(creator_key)
    if creator_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid creator key {creator_key!r}: expected creator:<external-person-id>",
        )

    # Check if creator exists in user's library without loading full details
    from app.repositories.creator_summary import load_creator_summary_inputs

    inputs = await load_creator_summary_inputs(db, current_user.id)
    exists = any(
        credit.external_id == creator_id
        for credits in inputs.issue_creator_credits.values()
        for credit in credits
    )

    return {"exists": exists}


__all__ = [
    "router",
]

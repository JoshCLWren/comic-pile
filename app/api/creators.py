"""Bounded personal creator summary API (issue #2028).

Endpoints:

- ``GET /api/v1/creators/summaries`` — bounded batch summary of the
  authenticated user's library statistics per canonical creator key.

This router validates requests and delegates aggregation to the creator summary
service. It performs no query construction and no direct persistence.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.creator_summary import CreatorSummariesResponse
from app.services.creator_summary import get_creator_summaries

router = APIRouter(prefix="/api/v1/creators", tags=["creators"])

#: Upper bound for a single batch summary request (issue #2028 performance scope).
#: One request never grows past a small fixed number of queries and bounded rows.
MAX_CREATOR_KEYS = 50


def _split_creator_keys(raw: str) -> list[str]:
    """Split and de-duplicate the raw comma-separated keys parameter.

    Args:
        raw: Raw ``keys`` query parameter value.

    Returns:
        Unique, order-preserving creator keys.
    """
    seen: set[str] = set()
    keys: list[str] = []
    for part in raw.split(","):
        key = part.strip()
        if key and key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


def _validate_creator_keys(raw: str | None) -> list[str]:
    """Validate a creator keys query parameter into a bounded key list.

    Args:
        raw: Raw ``keys`` query parameter value.

    Returns:
        Unique validated creator keys.

    Raises:
        HTTPException: When the parameter is missing, unbounded, or malformed.
    """
    if not raw or not raw.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="keys must be a non-empty comma-separated list of creator keys",
        )

    keys = _split_creator_keys(raw)
    if not keys:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="keys must be a non-empty comma-separated list of creator keys",
        )

    if len(keys) > MAX_CREATOR_KEYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"keys may list at most {MAX_CREATOR_KEYS} creators per request",
        )

    for key in keys:
        parts = key.split(":")
        valid = len(parts) == 2 and parts[0] == "creator" and parts[1].isdigit()
        if not valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Invalid creator key {key!r}: expected creator:<external-person-id> "
                    "(stable ComicVine person id, no display names)"
                ),
            )

    return keys


@router.get("/summaries", response_model=CreatorSummariesResponse)
async def get_creator_summaries_endpoint(
    current_user: Annotated[User, Depends(get_current_user)],
    keys: str | None = Query(default=None, description="Comma-separated canonical creator keys"),
    db: AsyncSession = Depends(get_db),
) -> CreatorSummariesResponse:
    """Return bounded personal summary statistics for the requested creator keys.

    Only creator keys visible in the authenticated user's own confirmed issue
    metadata are summarized; unknown or foreign keys are silently omitted so a
    creator key can never leak another user's library state.

    Args:
        current_user: Authenticated user whose library is aggregated.
        keys: Comma-separated canonical creator keys.
        db: Async database session.

    Returns:
        Batch summary keyed by requested visible creator keys, plus explicit
        coverage state.

    Raises:
        HTTPException: When the ``keys`` parameter is missing, unbounded, or malformed.
    """
    requested_keys = _validate_creator_keys(keys)
    return await get_creator_summaries(db, current_user.id, requested_keys)


__all__ = [
    "MAX_CREATOR_KEYS",
    "router",
]
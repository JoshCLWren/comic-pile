"""Bounded personal creator summary and discovery APIs (issues #2028, #2775).

Endpoints:

- ``GET /api/v1/creators`` — bounded discovery list of canonical creators with
  at least one rated issue for the authenticated user (issue #2775).
- ``GET /api/v1/creators/summaries`` — bounded batch summary of the
  authenticated user's library statistics per canonical creator key.

This router validates requests and delegates aggregation to the creator services.
It performs no query construction and no direct persistence.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.creator_detail import CreatorDetailResponse
from app.schemas.creator_list import CreatorListResponse
from app.schemas.creator_summary import CreatorSummariesResponse
from app.services.creator_detail import get_creator_detail
from app.services.creator_list import get_creator_list
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


@router.get("", response_model=CreatorListResponse, include_in_schema=True)
@router.get("/", response_model=CreatorListResponse, include_in_schema=False)
async def list_creators_endpoint(
    current_user: Annotated[User, Depends(get_current_user)],
    search: str | None = Query(
        default=None,
        description="Bounded case-insensitive name substring",
        max_length=100,
    ),
    sort: Literal["name", "ratings_count", "average_rating"] = Query(
        default="name",
        description="Browse ordering: name (alphabetical), ratings_count (most-rated), "
        "average_rating (personal average desc, nulls last)",
    ),
    limit: int = Query(
        default=20,
        ge=1,
        le=50,
        description="Page size (bounded, max 50)",
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="Page offset",
    ),
    db: AsyncSession = Depends(get_db),
) -> CreatorListResponse:
    """Return bounded personal creator discovery list for the authenticated user.

    The default collection is creators with at least one rated issue for the
    current user (headline-eligible rating). Rows include canonical key, display
    name, personal ratings count, personal average rating, and compact normalized
    roles. Ordering is deterministic with a stable canonical-key tie-breaker so
    pagination is correct across pages. Name search is bounded and user-scoped.
    ``average_rating`` sorting handles ``null`` explicitly (nulls last) so the
    contract remains deterministic if filtering expands to include unrated
    creators later.

    Args:
        current_user: Authenticated user whose library is aggregated.
        search: Optional bounded case-insensitive name substring.
        sort: Deterministic browse ordering.
        limit: Bounded page size.
        offset: Page offset.
        db: Async database session.

    Returns:
        Bounded creator list with deterministic ordering and coverage state.
    """
    bounded_search = search.strip() if search and search.strip() else None
    if bounded_search and len(bounded_search) > 100:
        bounded_search = bounded_search[:100]
    return await get_creator_list(
        db,
        current_user.id,
        search=bounded_search,
        sort=sort,
        limit=limit,
        offset=offset,
    )


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


@router.get("/{creator_key}", response_model=CreatorDetailResponse)
async def get_creator_detail_endpoint(
    creator_key: str,
    current_user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(50, ge=1, le=100),
    offset: int | None = Query(None, ge=0),
    db: AsyncSession = Depends(get_db),
) -> CreatorDetailResponse:
    """Return full personal creator detail for the specified canonical key.

    Args:
        creator_key: Canonical creator key (e.g. ``creator:12345``).
        current_user: Authenticated user owning the library.
        limit: Max number of issues per collection.
        offset: Pagination offset.
        db: Async database session.

    Returns:
        The full creator detail response including summary, role stats, and issue lists.

    Raises:
        HTTPException: When the key is malformed or the creator is not found
        in the user's library.
    """
    try:
        return await get_creator_detail(
            db=db,
            user_id=current_user.id,
            creator_key=creator_key,
            limit=limit,
            offset=offset,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Creator {creator_key} not found in your library",
        ) from None


__all__ = [
    "MAX_CREATOR_KEYS",
    "router",
]
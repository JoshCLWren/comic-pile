"""Bounded personal creator summary, discovery, and comparison APIs (issues #2028, #2775, #3091, #3176).

Endpoints:

- ``GET /api/v1/creators`` — bounded discovery list of canonical creators with
  at least one rated issue for the authenticated user (issue #2775).
- ``GET /api/v1/creators/summaries`` — bounded batch summary of the
  authenticated user's library statistics per canonical creator key.
- ``GET /api/v1/creators/compare`` — bounded side-by-side comparison of 2-4
  canonical creators using shared personal analytics semantics (issue #3091).
- ``GET /api/v1/creators/compare/<metric>`` — bounded evidence pages that
  explain one comparison metric: its exact calculation and the paginated
  issue set behind it (issue #3176).
- ``GET /api/v1/creators/{creator_key}`` — bounded personal creator detail,
  including series/run-level aggregates (issues #2037, #3088).
- ``GET /api/v1/creators/{creator_key}/series/{series_key}/issues`` — bounded
  drill-down of the issues behind one series/run aggregate (issue #3088).

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
from app.schemas.creator_comparison import (
    CreatorAverageDrilldownResponse,
    CreatorComparisonResponse,
    CreatorDistributionDrilldownResponse,
    CreatorFiveStarRateDrilldownResponse,
    CreatorMedianDrilldownResponse,
    CreatorReadWithoutRatingDrilldownResponse,
    CreatorRoleAverageDrilldownResponse,
    CreatorSeriesAverageDrilldownResponse,
    CreatorUnreadDrilldownResponse,
)
from app.schemas.creator_detail import CreatorDetailResponse, CreatorSeriesIssueListResponse
from app.schemas.creator_list import CreatorListResponse
from app.schemas.creator_summary import CreatorSummariesResponse
from app.services.creator_comparison import (
    DRILLDOWN_PAGE_SIZE_MAX,
    get_5_star_rate_drilldown,
    get_average_drilldown,
    get_creator_comparison,
    get_median_drilldown,
    get_rating_distribution_drilldown,
    get_read_without_rating_drilldown,
    get_role_average_drilldown,
    get_series_average_drilldown,
    get_unread_drilldown,
)
from app.services.creator_detail import get_creator_detail, get_creator_series_issues
from app.services.creator_list import get_creator_list
from app.services.creator_summary import get_creator_summaries

router = APIRouter(prefix="/api/v1/creators", tags=["creators"])

#: Upper bound for a single batch summary request (issue #2028 performance scope).
#: One request never grows past a small fixed number of queries and bounded rows.
MAX_CREATOR_KEYS = 50

#: Bounded comparison limits (issue #3091).
MIN_COMPARISON_CREATORS = 2
MAX_COMPARISON_CREATORS = 4


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


def _validate_comparison_keys(raw: str | None) -> list[str]:
    """Validate a creator keys query parameter for comparison (2-4 keys).

    Args:
        raw: Raw ``keys`` query parameter value.

    Returns:
        Unique validated creator keys (2-4).

    Raises:
        HTTPException: When the parameter is missing, out of bounds, or malformed.
    """
    if not raw or not raw.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"keys must be a comma-separated list of {MIN_COMPARISON_CREATORS}-"
                f"{MAX_COMPARISON_CREATORS} canonical creator keys"
            ),
        )

    keys = _split_creator_keys(raw)
    if not keys:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"keys must be a comma-separated list of {MIN_COMPARISON_CREATORS}-"
                f"{MAX_COMPARISON_CREATORS} canonical creator keys"
            ),
        )

    if len(keys) < MIN_COMPARISON_CREATORS or len(keys) > MAX_COMPARISON_CREATORS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"keys must contain {MIN_COMPARISON_CREATORS} to {MAX_COMPARISON_CREATORS} "
                f"creator keys, got {len(keys)}"
            ),
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
    min_ratings: int = Query(
        default=0,
        ge=0,
        description="Minimum rated-sample filter (0 = any sample size)",
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
        min_ratings: Minimum rated-sample filter for browse.
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
        min_ratings=min_ratings,
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


@router.get("/compare", response_model=CreatorComparisonResponse)
async def compare_creators_endpoint(
    current_user: Annotated[User, Depends(get_current_user)],
    keys: str | None = Query(
        default=None,
        description=f"Comma-separated canonical creator keys ({MIN_COMPARISON_CREATORS}-{MAX_COMPARISON_CREATORS})",
    ),
    db: AsyncSession = Depends(get_db),
) -> CreatorComparisonResponse:
    """Return bounded personal side-by-side comparison for the requested creator keys.

    Compares 2-4 canonical creators using the same explainable personal analytics
    already available on creator detail pages. Every metric remains explicitly
    personal to the authenticated user.

    Metrics included per creator:
    - Average rating and median rating
    - Rated sample count
    - Rating distribution
    - 5★/top-rating rate (proportion of 5.0 ratings)
    - Role-specific averages and counts
    - Strongest series/thread aggregates
    - Unread/upcoming attributed issue count
    - Read-but-unrated attributed issue count
    - Explicit "insufficient data" flag when rated sample < 3

    Only creator keys visible in the authenticated user's own confirmed issue
    metadata are compared; unknown or foreign keys are silently omitted so a
    creator key can never leak another user's library state. Same-display-name
    creators remain distinct via their canonical keys.

    Args:
        current_user: Authenticated user whose library is aggregated.
        keys: Comma-separated canonical creator keys (2-4).
        db: Async database session.

    Returns:
        Batch comparison keyed by requested visible creator keys, plus explicit
        coverage state and list of keys with insufficient data.

    Raises:
        HTTPException: When the ``keys`` parameter is missing, out of bounds, or malformed.
    """
    requested_keys = _validate_comparison_keys(keys)
    try:
        return await get_creator_comparison(db, current_user.id, requested_keys)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


def _drilldown_error(creator: str, error: Exception) -> HTTPException:
    """Map drilldown service errors onto their HTTP contract.

    Args:
        creator: The requested canonical creator key, for the not-found body.
        error: The service error (``ValueError`` for malformed keys, buckets,
            or cursors; ``KeyError`` for a creator or series absent from the
            user's library).

    Returns:
        The mapped HTTP error; the caller must still raise it.
    """
    if isinstance(error, KeyError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Creator {creator} not found in your library",
        )
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))


@router.get("/compare/average", response_model=CreatorAverageDrilldownResponse)
async def get_average_drilldown_endpoint(
    current_user: Annotated[User, Depends(get_current_user)],
    creator: str = Query(
        ...,
        description="Canonical creator key (e.g. ``creator:12345``)",
    ),
    limit: int = Query(50, ge=1, le=DRILLDOWN_PAGE_SIZE_MAX),
    cursor: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> CreatorAverageDrilldownResponse:
    """Return the average rating evidence page for one creator (issue #3176).

    The calculation and issue set use the exact shared aggregation semantics
    as the comparison summary, so the summary value and drilldown always
    reconcile. The same page also serves the rated-issue-count metric: its
    evidence set is the complete rated headline sample.
    """
    try:
        return await get_average_drilldown(
            db, current_user.id, creator, limit=limit, cursor=cursor
        )
    except (ValueError, KeyError) as e:
        raise _drilldown_error(creator, e) from e


@router.get("/compare/median", response_model=CreatorMedianDrilldownResponse)
async def get_median_drilldown_endpoint(
    current_user: Annotated[User, Depends(get_current_user)],
    creator: str = Query(
        ...,
        description="Canonical creator key (e.g. ``creator:12345``)",
    ),
    limit: int = Query(50, ge=1, le=DRILLDOWN_PAGE_SIZE_MAX),
    cursor: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> CreatorMedianDrilldownResponse:
    """Return the median rating evidence page for one creator (issue #3176)."""
    try:
        return await get_median_drilldown(
            db, current_user.id, creator, limit=limit, cursor=cursor
        )
    except (ValueError, KeyError) as e:
        raise _drilldown_error(creator, e) from e


@router.get("/compare/distribution", response_model=CreatorDistributionDrilldownResponse)
async def get_rating_distribution_drilldown_endpoint(
    current_user: Annotated[User, Depends(get_current_user)],
    creator: str = Query(
        ...,
        description="Canonical creator key (e.g. ``creator:12345``)",
    ),
    bucket: str = Query(
        ...,
        description="Rating bucket key (one of ``5``, ``4.5``, ``4``, ``3.5``, ``3``, ``2.5``, ``2``, ``1.5``, ``1``)",
    ),
    limit: int = Query(50, ge=1, le=DRILLDOWN_PAGE_SIZE_MAX),
    cursor: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> CreatorDistributionDrilldownResponse:
    """Return one rating-distribution bucket evidence page (issue #3176)."""
    try:
        return await get_rating_distribution_drilldown(
            db, current_user.id, creator, bucket, limit=limit, cursor=cursor
        )
    except (ValueError, KeyError) as e:
        raise _drilldown_error(creator, e) from e


@router.get("/compare/5-star-rate", response_model=CreatorFiveStarRateDrilldownResponse)
async def get_5_star_rate_drilldown_endpoint(
    current_user: Annotated[User, Depends(get_current_user)],
    creator: str = Query(
        ...,
        description="Canonical creator key (e.g. ``creator:12345``)",
    ),
    limit: int = Query(50, ge=1, le=DRILLDOWN_PAGE_SIZE_MAX),
    cursor: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> CreatorFiveStarRateDrilldownResponse:
    """Return the 5-star rate evidence page for one creator (issue #3176)."""
    try:
        return await get_5_star_rate_drilldown(
            db, current_user.id, creator, limit=limit, cursor=cursor
        )
    except (ValueError, KeyError) as e:
        raise _drilldown_error(creator, e) from e


@router.get("/compare/role-average", response_model=CreatorRoleAverageDrilldownResponse)
async def get_role_average_drilldown_endpoint(
    current_user: Annotated[User, Depends(get_current_user)],
    creator: str = Query(
        ...,
        description="Canonical creator key (e.g. ``creator:12345``)",
    ),
    role: str = Query(
        ...,
        description="Role name (e.g. ``writer``, ``artist``, ``penciler``, ``inker``, ``colorist``, ``letterer``)",
    ),
    limit: int = Query(50, ge=1, le=DRILLDOWN_PAGE_SIZE_MAX),
    cursor: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> CreatorRoleAverageDrilldownResponse:
    """Return one role's credited-issue and average evidence page (issue #3176)."""
    try:
        return await get_role_average_drilldown(
            db, current_user.id, creator, role, limit=limit, cursor=cursor
        )
    except (ValueError, KeyError) as e:
        raise _drilldown_error(creator, e) from e


@router.get("/compare/series-average", response_model=CreatorSeriesAverageDrilldownResponse)
async def get_series_average_drilldown_endpoint(
    current_user: Annotated[User, Depends(get_current_user)],
    creator: str = Query(
        ...,
        description="Canonical creator key (e.g. ``creator:12345``)",
    ),
    series: str = Query(
        ...,
        description="Canonical series key (e.g. ``thread:123``)",
    ),
    limit: int = Query(50, ge=1, le=DRILLDOWN_PAGE_SIZE_MAX),
    cursor: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> CreatorSeriesAverageDrilldownResponse:
    """Return one series' attributed-issue and average evidence page (issue #3176)."""
    try:
        return await get_series_average_drilldown(
            db, current_user.id, creator, series, limit=limit, cursor=cursor
        )
    except (ValueError, KeyError) as e:
        raise _drilldown_error(creator, e) from e


@router.get(
    "/compare/read-without-rating", response_model=CreatorReadWithoutRatingDrilldownResponse
)
async def get_read_without_rating_drilldown_endpoint(
    current_user: Annotated[User, Depends(get_current_user)],
    creator: str = Query(
        ...,
        description="Canonical creator key (e.g. ``creator:12345``)",
    ),
    limit: int = Query(50, ge=1, le=DRILLDOWN_PAGE_SIZE_MAX),
    cursor: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> CreatorReadWithoutRatingDrilldownResponse:
    """Return the read-without-rating evidence page for one creator (issue #3176)."""
    try:
        return await get_read_without_rating_drilldown(
            db, current_user.id, creator, limit=limit, cursor=cursor
        )
    except (ValueError, KeyError) as e:
        raise _drilldown_error(creator, e) from e


@router.get("/compare/unread", response_model=CreatorUnreadDrilldownResponse)
async def get_unread_drilldown_endpoint(
    current_user: Annotated[User, Depends(get_current_user)],
    creator: str = Query(
        ...,
        description="Canonical creator key (e.g. ``creator:12345``)",
    ),
    limit: int = Query(50, ge=1, le=DRILLDOWN_PAGE_SIZE_MAX),
    cursor: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> CreatorUnreadDrilldownResponse:
    """Return the unread/attributed-unread evidence page for one creator (issue #3176)."""
    try:
        return await get_unread_drilldown(
            db, current_user.id, creator, limit=limit, cursor=cursor
        )
    except (ValueError, KeyError) as e:
        raise _drilldown_error(creator, e) from e


@router.get("/{creator_key}/series/{series_key}/issues", response_model=CreatorSeriesIssueListResponse)
async def get_creator_series_issues_endpoint(
    creator_key: str,
    series_key: str,
    current_user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(50, ge=1, le=100),
    offset: int | None = Query(None, ge=0),
    db: AsyncSession = Depends(get_db),
) -> CreatorSeriesIssueListResponse:
    """Return the bounded issues supporting one creator series/run group.

    Every series aggregate on creator detail is explainable from these rows.
    The series key must be the canonical ``thread:<id>`` identity; a group is
    never addressed by display-title text, and a series belonging to another
    user is indistinguishable from one that does not exist.

    Args:
        creator_key: Canonical creator key (e.g. ``creator:12345``).
        series_key: Canonical series key (e.g. ``thread:7``).
        current_user: Authenticated user owning the library.
        limit: Max number of issue rows.
        offset: Pagination offset.
        db: Async database session.

    Returns:
        The bounded drill-down page plus its group-level header aggregates.

    Raises:
        HTTPException: When either key is malformed, or the creator or series
        group is not found in the user's library.
    """
    try:
        return await get_creator_series_issues(
            db=db,
            user_id=current_user.id,
            creator_key=creator_key,
            series_key=series_key,
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
            detail=f"Series {series_key} not found in your library",
        ) from None


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
    "MIN_COMPARISON_CREATORS",
    "MAX_COMPARISON_CREATORS",
    "router",
]
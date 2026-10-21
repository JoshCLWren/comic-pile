"""Read-only reverse lookup of CBL source lists by exact Comic Vine issue identity.

The lookup answers a shared-catalog question: which CBLs in the fork contain
one exact Comic Vine issue ID, and at which source positions. The result never
depends on the calling reader, so a reader with no owned Issues sees the same
answer as a reader who owns the matching comic.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.cbl_comicvine_lookup import (
    CBLComicvineOccurrenceDetail,
    CBLComicvineOccurrencePage,
)
from app.services.cbl_comicvine_lookup_service import (
    search_cbl_sources_by_comicvine_issue,
)

router = APIRouter(prefix="/issue-identity", tags=["issue-identity"])

DEFAULT_OCCURRENCE_LIMIT = 50
MAX_OCCURRENCE_LIMIT = 200


@router.get(
    "/cbl-sources/by-comicvine-issue/{comicvine_issue_id}",
    response_model=CBLComicvineOccurrencePage,
)
async def find_cbl_sources_by_comicvine_issue(
    comicvine_issue_id: Annotated[str, Path(min_length=1, max_length=100)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_OCCURRENCE_LIMIT)] = DEFAULT_OCCURRENCE_LIMIT,
) -> CBLComicvineOccurrencePage:
    """Return every CBL source position that holds one exact Comic Vine issue.

    The match is exact on the Comic Vine issue identity, so a shared series
    title, a shared volume, or the same issue number in another volume never
    produces a false positive. Repeated occurrences inside one source list
    stay separate rows, and the same identity in several source lists is
    reported once per list. The answer is shared catalog data: it never
    depends on the calling reader's owned Issues.

    Args:
        comicvine_issue_id: Exact Comic Vine issue external ID.
        current_user: Authenticated reader. Unused: the shared catalog answer
            must not vary by reader.
        db: Async database session.
        offset: Zero-based index of the first returned source occurrence.
        limit: Maximum number of source occurrences to return.

    Returns:
        The matching source occurrences with the total occurrence count and
        the number of distinct source lists containing the identity.

    Raises:
        HTTPException: 422 when the supplied Comic Vine issue ID is blank.
    """
    del current_user
    normalized_issue_id = comicvine_issue_id.strip()
    if not normalized_issue_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Comic Vine issue ID must not be blank",
        )

    page = await search_cbl_sources_by_comicvine_issue(
        db,
        comicvine_issue_id=normalized_issue_id,
        offset=offset,
        limit=limit,
    )
    return CBLComicvineOccurrencePage(
        comicvine_issue_id=page.comicvine_issue_id,
        occurrences_total=page.occurrences_total,
        lists_total=page.lists_total,
        occurrences_offset=page.occurrences_offset,
        occurrences_limit=page.occurrences_limit,
        occurrences=[
            CBLComicvineOccurrenceDetail(
                list_id=occurrence.list_id,
                list_name=occurrence.list_name,
                source_path=occurrence.source_path,
                source_repository=occurrence.source_repository,
                source_ref=occurrence.source_ref,
                revision_sha=occurrence.revision_sha,
                position=occurrence.position,
                series_name=occurrence.series_name,
                issue_number=occurrence.issue_number,
                volume_year=occurrence.volume_year,
                publication_year=occurrence.publication_year,
                comicvine_issue_id=occurrence.comicvine_issue_id,
                comicvine_volume_id=occurrence.comicvine_volume_id,
            )
            for occurrence in page.occurrences
        ],
    )

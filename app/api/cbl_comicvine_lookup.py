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
    CBLReadingListCandidatesResponse,
    CBLReadingListInputEntry,
    CBLSourceComparisonMatch,
    CBLSourceComparisonRequest,
    CBLSourceComparisonResponse,
)
from app.services.cbl_comicvine_lookup_service import (
    CBLSourceComparisonMatch as CBLSourceComparisonMatchRow,
    compare_cbl_sources_by_comicvine_issues,
    get_reading_list_cbl_candidates,
    search_cbl_sources_by_comicvine_issue,
)

router = APIRouter(prefix="/issue-identity", tags=["issue-identity"])

DEFAULT_OCCURRENCE_LIMIT = 50
MAX_OCCURRENCE_LIMIT = 200
DEFAULT_COMPARISON_LIMIT = 50
MAX_COMPARISON_LIMIT = 100


def _comparison_match_response(
    match: CBLSourceComparisonMatchRow,
) -> CBLSourceComparisonMatch:
    """Map one service comparison row to its public response schema.

    Args:
        match: Service-level source comparison dataclass.

    Returns:
        The public comparison schema.
    """
    return CBLSourceComparisonMatch.model_validate(match, from_attributes=True)


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


@router.post("/cbl-sources/compare", response_model=CBLSourceComparisonResponse)
async def compare_cbl_sources(
    payload: CBLSourceComparisonRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=MAX_COMPARISON_LIMIT)] = DEFAULT_COMPARISON_LIMIT,
) -> CBLSourceComparisonResponse:
    """Rank shared CBL sources by exact coverage and relative order.

    The comparison receives confirmed Comic Vine issue IDs, never reader Issue
    IDs. It reads only the shared catalog, so one reader's owned collection
    cannot change the answer. Coverage counts distinct exact identities while
    repeated source occurrences remain visible, and same-titled volumes never
    match by title or issue number.

    Args:
        payload: Distinct confirmed Comic Vine issue IDs in intended order.
        current_user: Authenticated reader. Unused: the shared catalog answer
            must not vary by reader.
        db: Async database session.
        limit: Maximum number of ranked source lists to return.

    Returns:
        Ranked source comparisons with coverage, duplicate, and order evidence.
    """
    del current_user
    page = await compare_cbl_sources_by_comicvine_issues(
        db,
        comicvine_issue_ids=tuple(payload.comicvine_issue_ids),
        limit=limit,
    )
    return CBLSourceComparisonResponse(
        comicvine_issue_ids=list(page.comicvine_issue_ids),
        input_total=page.input_total,
        candidates_total=page.candidates_total,
        candidates=[_comparison_match_response(match) for match in page.candidates],
    )


@router.get(
    "/reading-lists/{list_id}/cbl-candidates",
    response_model=CBLReadingListCandidatesResponse,
)
async def find_cbl_candidates_for_reading_list(
    list_id: Annotated[int, Path(ge=1)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=MAX_COMPARISON_LIMIT)] = DEFAULT_COMPARISON_LIMIT,
) -> CBLReadingListCandidatesResponse:
    """Find shared CBL sources that cover one owned Reading List.

    Only distinct confirmed Comic Vine issue IDs from the reader's Issues are
    used to query the shared catalog. Entries without a confirmed ID, and
    entries with conflicting confirmed IDs, are returned as explicit gaps so
    the caller never substitutes a title/issue-number guess or claims that no
    CBL exists.

    Args:
        list_id: Owned Reading List identifier.
        current_user: Authenticated owner of the Reading List.
        db: Async database session.
        limit: Maximum number of ranked source lists to return.

    Returns:
        Every list entry's identity state plus ranked source comparisons.
    """
    result = await get_reading_list_cbl_candidates(
        db,
        user_id=current_user.id,
        list_id=list_id,
        limit=limit,
    )
    return CBLReadingListCandidatesResponse(
        list_id=result.list_id,
        list_name=result.list_name,
        input_entry_count=result.input_entry_count,
        input_confirmed_total=result.input_confirmed_total,
        input_missing_count=result.input_missing_count,
        input_conflict_count=result.input_conflict_count,
        input_ids=list(result.input_ids),
        entries=[
            CBLReadingListInputEntry(
                position=entry.position,
                issue_id=entry.issue_id,
                series_name=entry.series_name,
                issue_number=entry.issue_number,
                comicvine_issue_id=entry.comicvine_issue_id,
                comicvine_issue_ids=list(entry.comicvine_issue_ids),
                identity_status=entry.identity_status,
            )
            for entry in result.entries
        ],
        candidates_total=result.candidates_total,
        candidates=[
            _comparison_match_response(match) for match in result.candidates
        ],
    )

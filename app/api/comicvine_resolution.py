"""API routes for ComicVine identity resolution and metadata correction.

Provides user-facing endpoints for searching ComicVine series/issues,
inspecting/confirming/replacing identity mappings, and applying canonical
metadata corrections directly from the Roll experience.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.external_identities import ExternalIdentityMappingError
from app.models.user import User
from app.schemas.comicvine_resolution import (
    ComicVineSeriesIssuesResponse,
    ComicVineSeriesSearchResponse,
    ConfirmIdentityRequest,
    IssueIdentityResponse,
    MetadataCorrectionRevertRequest,
    MetadataCorrectionRequest,
    MetadataCorrectionsResponse,
    MetadataRefreshResponse,
    ReplaceIdentityRequest,
)
from app.services.comicvine_resolution import (
    apply_metadata_correction,
    confirm_comicvine_identity,
    get_comicvine_series_issues,
    get_issue_identity_state,
    list_metadata_corrections,
    request_provider_refresh,
    replace_comicvine_identity,
    revert_metadata_correction,
    search_comicvine_series,
)
from app.services.ownership import get_owned_issue_or_404

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/comicvine", tags=["comicvine-resolution"])


def _get_comicvine_client():
    """Build a ComicVine client from environment settings.

    Returns the client or None if ComicVine API key is not configured.
    """
    import os
    from pathlib import Path

    api_key = os.environ.get("COMICVINE_API_KEY", "").strip()
    if not api_key:
        return None

    from comic_pile.comicvine_provider import ComicVineClient

    cache_dir = Path(os.environ.get("COMICVINE_CACHE_DIR", "/tmp/comicpile-comicvine"))
    return ComicVineClient(api_key=api_key, cache_dir=cache_dir)


@router.get(
    "/search/series",
    response_model=ComicVineSeriesSearchResponse,
)
async def api_search_comicvine_series(
    current_user: Annotated[User, Depends(get_current_user)],
    q: str = Query(..., min_length=1, max_length=200, description="Series search query"),
    limit: int = Query(10, ge=1, le=50, description="Maximum results"),
) -> ComicVineSeriesSearchResponse:
    """Search ComicVine for series/volumes by title.

    Args:
        q: Search query string.
        limit: Maximum results to return.
        current_user: Authenticated user.
    """
    client = _get_comicvine_client()
    return await search_comicvine_series(client, q, limit=limit)


@router.get(
    "/series/{comicvine_volume_id}/issues",
    response_model=ComicVineSeriesIssuesResponse,
)
async def api_get_series_issues(
    comicvine_volume_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    series_name: str = Query("", description="Optional pre-fetched series name"),
) -> ComicVineSeriesIssuesResponse:
    """Fetch all issues within a ComicVine series/volume.

    Args:
        comicvine_volume_id: ComicVine volume ID.
        series_name: Optional series name to avoid extra API call.
        current_user: Authenticated user.
    """
    client = _get_comicvine_client()
    return await get_comicvine_series_issues(
        client, comicvine_volume_id, series_name=series_name
    )


@router.get(
    "/issues/{issue_id}/identity",
    response_model=IssueIdentityResponse,
)
async def api_get_issue_identity(
    issue_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> IssueIdentityResponse:
    """Return the current ComicVine identity state for a ComicPile issue.

    Shows confirmed, candidate, and unresolved mappings.

    Args:
        issue_id: ComicPile issue ID.
        current_user: Authenticated owner.
        db: Async database session.
    """
    await get_owned_issue_or_404(db, current_user.id, issue_id)
    try:
        return await get_issue_identity_state(
            db, user_id=current_user.id, issue_id=issue_id
        )
    except ExternalIdentityMappingError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post(
    "/issues/{issue_id}/identity:confirm",
    response_model=IssueIdentityResponse,
    status_code=status.HTTP_200_OK,
)
async def api_confirm_identity(
    issue_id: int,
    request: ConfirmIdentityRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> IssueIdentityResponse:
    """Confirm a ComicVine identity for an issue.

    Creates the mapping if it doesn't exist, or confirms an existing candidate.

    Args:
        issue_id: ComicPile issue ID.
        request: Confirmation request with comicvine_issue_id.
        current_user: Authenticated owner.
        db: Async database session.
    """
    await get_owned_issue_or_404(db, current_user.id, issue_id)
    try:
        await confirm_comicvine_identity(
            db,
            user_id=current_user.id,
            issue_id=issue_id,
            comicvine_issue_id=request.comicvine_issue_id,
        )
        await db.commit()
        return await get_issue_identity_state(
            db, user_id=current_user.id, issue_id=issue_id
        )
    except ExternalIdentityMappingError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post(
    "/issues/{issue_id}/identity:replace",
    response_model=IssueIdentityResponse,
    status_code=status.HTTP_200_OK,
)
async def api_replace_identity(
    issue_id: int,
    request: ReplaceIdentityRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> IssueIdentityResponse:
    """Replace the current confirmed ComicVine identity with a new one.

    Demotes the old mapping and confirms the new one atomically.

    Args:
        issue_id: ComicPile issue ID.
        request: Replace request with new comicvine_issue_id and optional reason.
        current_user: Authenticated owner.
        db: Async database session.
    """
    await get_owned_issue_or_404(db, current_user.id, issue_id)
    try:
        await replace_comicvine_identity(
            db,
            user_id=current_user.id,
            issue_id=issue_id,
            comicvine_issue_id=request.comicvine_issue_id,
            reason=request.reason,
        )
        await db.commit()
        return await get_issue_identity_state(
            db, user_id=current_user.id, issue_id=issue_id
        )
    except ExternalIdentityMappingError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post(
    "/issues/{issue_id}/metadata:refresh",
    response_model=MetadataRefreshResponse,
    status_code=status.HTTP_200_OK,
)
async def api_refresh_metadata(
    issue_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> MetadataRefreshResponse:
    """Request a ComicVine metadata refresh for an issue with a confirmed identity.

    Returns the confirmed ComicVine issue ID for the caller to trigger hydration.

    Args:
        issue_id: ComicPile issue ID.
        current_user: Authenticated owner.
        db: Async database session.
    """
    await get_owned_issue_or_404(db, current_user.id, issue_id)
    return await request_provider_refresh(
        db, user_id=current_user.id, issue_id=issue_id
    )


@router.post(
    "/issues/{issue_id}/metadata:correct",
    response_model=MetadataCorrectionsResponse,
    status_code=status.HTTP_200_OK,
)
async def api_apply_correction(
    issue_id: int,
    request: MetadataCorrectionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> MetadataCorrectionsResponse:
    """Apply a canonical metadata correction to an issue.

    The correction preserves the provider's raw value alongside the canonical override.

    Args:
        issue_id: ComicPile issue ID.
        request: Correction request with field_name and canonical_value.
        current_user: Authenticated owner.
        db: Async database session.
    """
    await get_owned_issue_or_404(db, current_user.id, issue_id)
    try:
        await apply_metadata_correction(
            db,
            user_id=current_user.id,
            issue_id=issue_id,
            request=request,
        )
        await db.commit()
        return await list_metadata_corrections(
            db, user_id=current_user.id, issue_id=issue_id
        )
    except ExternalIdentityMappingError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/issues/{issue_id}/metadata:corrections",
    response_model=MetadataCorrectionsResponse,
)
async def api_list_corrections(
    issue_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> MetadataCorrectionsResponse:
    """List all active corrections for an issue.

    Args:
        issue_id: ComicPile issue ID.
        current_user: Authenticated owner.
        db: Async database session.
    """
    await get_owned_issue_or_404(db, current_user.id, issue_id)
    return await list_metadata_corrections(
        db, user_id=current_user.id, issue_id=issue_id
    )


@router.post(
    "/issues/{issue_id}/metadata:revert",
    response_model=MetadataCorrectionsResponse,
    status_code=status.HTTP_200_OK,
)
async def api_revert_correction(
    issue_id: int,
    request: MetadataCorrectionRevertRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> MetadataCorrectionsResponse:
    """Revert a metadata correction (soft-delete with audit trail).

    Args:
        issue_id: ComicPile issue ID.
        request: Revert request with correction_id.
        current_user: Authenticated owner.
        db: Async database session.
    """
    await get_owned_issue_or_404(db, current_user.id, issue_id)
    try:
        await revert_metadata_correction(
            db,
            user_id=current_user.id,
            issue_id=issue_id,
            correction_id=request.correction_id,
        )
        await db.commit()
        return await list_metadata_corrections(
            db, user_id=current_user.id, issue_id=issue_id
        )
    except ExternalIdentityMappingError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

"""Catalog API endpoints for shared comic series and issue identities."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.auth import get_current_user
from app.models.user import User
from app.schemas.catalog import (
    ExternalIdentityUpsert,
    ExternalIdentityResponse,
    ThreadSeriesAttachRequest,
    ThreadSeriesAttachResponse,
    IssueAttachRequest,
    IssueAttachResponse,
    CatalogSeriesSearchResponse,
    CatalogIssueSearchResponse,
    ThreadExternalSeriesMappingResponse,
    IssueExternalIdentityMappingResponse,
)
from app.services.catalog import (
    upsert_catalog_series as upsert_catalog_series_svc,
    upsert_catalog_issue as upsert_catalog_issue_svc,
    attach_series_to_thread as attach_series_to_thread_svc,
    attach_issue_to_thread as attach_issue_to_thread_svc,
    search_catalog_series as search_catalog_series_svc,
    search_catalog_issues as search_catalog_issues_svc,
    list_series_mappings as list_series_mappings_svc,
    list_issue_mappings as list_issue_mappings_svc,
)

def _dt_to_ts(dt: datetime | None) -> float | None:
    """Convert datetime to Unix timestamp."""
    return dt.timestamp() if dt is not None else None


router = APIRouter(prefix="/api/v1", tags=["catalog"])


@router.get(
    "/catalog/series",
    response_model=list[CatalogSeriesSearchResponse],
)
async def search_catalog_series(
    search: str | None = Query(default=None, min_length=1, description="Search by series external_id"),
    provider: str | None = Query(default="comicvine", description="Filter by provider"),
    limit: int = Query(default=50, ge=1, le=100, description="Maximum number of results to return"),
    db: AsyncSession = Depends(get_db),
) -> list[CatalogSeriesSearchResponse]:
    """Search for canonical series in the shared catalog.

    Args:
        search: Optional search term to match against series external_id.
        provider: Filter by provider name (default: comicvine).
        limit: Maximum number of results to return (hard capped at 100).
        db: Database session.

    Returns:
        List of matching external identities for series.
    """
    identities = await search_catalog_series_svc(
        db,
        search=search,
        provider=provider or "comicvine",
        limit=limit,
    )
    return [
        CatalogSeriesSearchResponse(
            id=identity.id,
            provider=identity.provider,
            entity_type=identity.entity_type,
            external_id=identity.external_id,
            external_url=identity.external_url,
            metadata_json=identity.metadata_json,
            provider_updated_at=_dt_to_ts(identity.provider_updated_at),
            created_at=_dt_to_ts(identity.created_at),
            updated_at=_dt_to_ts(identity.updated_at),
        )
        for identity in identities
    ]


@router.get(
    "/catalog/issues",
    response_model=list[CatalogIssueSearchResponse],
)
async def search_catalog_issues(
    search: str | None = Query(default=None, min_length=1, description="Search by issue external_id"),
    provider: str | None = Query(default="comicvine", description="Filter by provider"),
    series_external_id: str | None = Query(
        default=None, description="Filter by series external_id (e.g., 4050-justice-league)"
    ),
    limit: int = Query(default=50, ge=1, le=100, description="Maximum number of results to return"),
    db: AsyncSession = Depends(get_db),
) -> list[CatalogIssueSearchResponse]:
    """Search for canonical issues in the shared catalog.

    Args:
        search: Optional search term to match against issue external_id.
        provider: Filter by provider name (default: comicvine).
        series_external_id: Filter by series external_id to scope the search.
        limit: Maximum number of results to return (hard capped at 100).
        db: Database session.

    Returns:
        List of matching external identities for issues.
    """
    identities = await search_catalog_issues_svc(
        db,
        search=search,
        provider=provider or "comicvine",
        series_external_id=series_external_id,
        limit=limit,
    )
    return [
        CatalogIssueSearchResponse(
            id=identity.id,
            provider=identity.provider,
            entity_type=identity.entity_type,
            external_id=identity.external_id,
            external_url=identity.external_url,
            metadata_json=identity.metadata_json,
            provider_updated_at=_dt_to_ts(identity.provider_updated_at),
            created_at=_dt_to_ts(identity.created_at),
            updated_at=_dt_to_ts(identity.updated_at),
        )
        for identity in identities
    ]


@router.post(
    "/catalog/series",
    response_model=ExternalIdentityResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upsert_catalog_series(
    request: ExternalIdentityUpsert,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ExternalIdentityResponse:
    """Upsert a canonical series into the shared catalog (idempotent).

    Creation is idempotent: if a canonical existing series can be identified,
    it is surfaced rather than silently duplicating a run.

    Args:
        request: Upsert request with provider, entity_type, external_id, and optional metadata.
        current_user: Authenticated user for authorization.
        db: Database session.

    Returns:
        The created or existing external identity.
    """
    identity = await upsert_catalog_series_svc(
        db,
        provider=request.provider,
        entity_type=request.entity_type,
        external_id=request.external_id,
        external_url=request.external_url,
        metadata_json=request.metadata_json,
    )

    return ExternalIdentityResponse(
        id=identity.id,
        provider=identity.provider,
        entity_type=identity.entity_type,
        external_id=identity.external_id,
        external_url=identity.external_url,
        metadata_json=identity.metadata_json,
        provider_updated_at=_dt_to_ts(identity.provider_updated_at),
        created_at=_dt_to_ts(identity.created_at),
        updated_at=_dt_to_ts(identity.updated_at),
    )


@router.post(
    "/catalog/issues",
    response_model=ExternalIdentityResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upsert_catalog_issue(
    request: ExternalIdentityUpsert,
    db: AsyncSession = Depends(get_db),
) -> ExternalIdentityResponse:
    """Upsert a canonical issue into the shared catalog (idempotent).

    Creation is idempotent: if a canonical existing issue can be identified,
    it is surfaced rather than silently duplicating a run.

    Args:
        request: Upsert request with provider, entity_type, external_id, and optional metadata.
        db: Database session.

    Returns:
        The created or existing external identity.
    """
    identity = await upsert_catalog_issue_svc(
        db,
        provider=request.provider,
        entity_type=request.entity_type,
        external_id=request.external_id,
        external_url=request.external_url,
        metadata_json=request.metadata_json,
    )

    return ExternalIdentityResponse(
        id=identity.id,
        provider=identity.provider,
        entity_type=identity.entity_type,
        external_id=identity.external_id,
        external_url=identity.external_url,
        metadata_json=identity.metadata_json,
        provider_updated_at=_dt_to_ts(identity.provider_updated_at),
        created_at=_dt_to_ts(identity.created_at),
        updated_at=_dt_to_ts(identity.updated_at),
    )


@router.post(
    "/threads/{thread_id}/series/{series_external_id}/attach",
    response_model=ThreadSeriesAttachResponse,
    status_code=status.HTTP_201_CREATED,
)
async def attach_series_to_thread(
    thread_id: int,
    series_external_id: str,
    request: ThreadSeriesAttachRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ThreadSeriesAttachResponse:
    """Attach a confirmed series identity to a user's reading thread.

    Args:
        thread_id: The thread to associate with the series.
        series_external_id: The external series identity external_id (e.g., ComicVine volume ID).
        request: Attachment request with status and optional evidence/confidence.
        current_user: Authenticated user for authorization.
        db: Database session.

    Returns:
        The created or updated thread-series mapping.
    """
    mapping = await attach_series_to_thread_svc(
        db,
        user_id=current_user.id,
        thread_id=thread_id,
        series_external_id=series_external_id,
        status=request.status,
        evidence_source=request.evidence_source,
        confidence=request.confidence,
    )

    return ThreadSeriesAttachResponse(
        id=mapping.id,
        thread_id=mapping.thread_id,
        external_identity_id=mapping.external_identity_id,
        status=mapping.status,
        evidence_source=mapping.evidence_source,
        confidence=mapping.confidence,
        created_at=_dt_to_ts(mapping.created_at),
        updated_at=_dt_to_ts(mapping.updated_at),
    )


@router.post(
    "/threads/{thread_id}/issues/{issue_id}/attach-external",
    response_model=IssueAttachResponse,
    status_code=status.HTTP_201_CREATED,
)
async def attach_issue_to_thread(
    thread_id: int,
    issue_id: int,
    request: IssueAttachRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> IssueAttachResponse:
    """Attach a confirmed issue identity to a user's reading thread.

    Args:
        thread_id: The thread to associate with the issue.
        issue_id: The internal ComicPile issue ID to attach the external identity to.
        request: Attachment request with external identity details and mapping status.
        current_user: Authenticated user for authorization.
        db: Database session.

    Returns:
        The created or updated issue-external identity mapping.
    """
    mapping = await attach_issue_to_thread_svc(
        db,
        user_id=current_user.id,
        thread_id=thread_id,
        issue_id=issue_id,
        provider=request.provider,
        entity_type=request.entity_type,
        external_id=request.external_id,
        external_url=request.external_url,
        metadata_json=request.metadata_json,
        status=request.status,
        evidence_source=request.evidence_source,
        confidence=request.confidence,
    )

    return IssueAttachResponse(
        id=mapping.id,
        issue_id=mapping.issue_id,
        external_identity_id=mapping.external_identity_id,
        status=mapping.status,
        evidence_source=mapping.evidence_source,
        confidence=mapping.confidence,
        rejection_reason=mapping.rejection_reason,
        created_at=_dt_to_ts(mapping.created_at),
        updated_at=_dt_to_ts(mapping.updated_at),
    )


@router.get(
    "/catalog/mappings/series",
    response_model=list[ThreadExternalSeriesMappingResponse],
)
async def list_series_mappings(
    thread_id: int | None = Query(default=None, description="Filter by thread_id"),
    status: str | None = Query(default=None, description="Filter by mapping status"),
    limit: int = Query(default=100, ge=1, le=500, description="Maximum number of results to return"),
    db: AsyncSession = Depends(get_db),
) -> list[ThreadExternalSeriesMappingResponse]:
    """List thread-series mappings (inspection endpoint).

    Read-only inspection may be public where safe.

    Args:
        thread_id: Optional filter by thread ID.
        status: Optional filter by mapping status.
        limit: Maximum number of results to return.
        db: Database session.

    Returns:
        List of thread-series mappings.
    """
    mappings = await list_series_mappings_svc(
        db,
        thread_id=thread_id,
        status=status,
        limit=limit,
    )
    return [
        ThreadExternalSeriesMappingResponse(
            id=mapping.id,
            thread_id=mapping.thread_id,
            external_identity_id=mapping.external_identity_id,
            status=mapping.status,
            evidence_source=mapping.evidence_source,
            confidence=mapping.confidence,
            created_at=_dt_to_ts(mapping.created_at),
            updated_at=_dt_to_ts(mapping.updated_at),
        )
        for mapping in mappings
    ]


@router.get(
    "/catalog/mappings/issues",
    response_model=list[IssueExternalIdentityMappingResponse],
)
async def list_issue_mappings(
    issue_id: int | None = Query(default=None, description="Filter by issue_id"),
    status: str | None = Query(default=None, description="Filter by mapping status"),
    limit: int = Query(default=100, ge=1, le=500, description="Maximum number of results to return"),
    db: AsyncSession = Depends(get_db),
) -> list[IssueExternalIdentityMappingResponse]:
    """List issue-external identity mappings (inspection endpoint).

    Read-only inspection may be public where safe.

    Args:
        issue_id: Optional filter by issue ID.
        status: Optional filter by mapping status.
        limit: Maximum number of results to return.
        db: Database session.

    Returns:
        List of issue-external identity mappings.
    """
    mappings = await list_issue_mappings_svc(
        db,
        issue_id=issue_id,
        status=status,
        limit=limit,
    )
    return [
        IssueExternalIdentityMappingResponse(
            id=mapping.id,
            issue_id=mapping.issue_id,
            external_identity_id=mapping.external_identity_id,
            status=mapping.status,
            evidence_source=mapping.evidence_source,
            confidence=mapping.confidence,
            rejection_reason=mapping.rejection_reason,
            created_at=_dt_to_ts(mapping.created_at),
            updated_at=_dt_to_ts(mapping.updated_at),
        )
        for mapping in mappings
    ]

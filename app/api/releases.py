"""Public read and service-authorized write API for What's New releases."""

import os
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.release import Release
from app.schemas.release import (
    PublicReleaseResponse,
    ReleaseListResponse,
    ReleaseResponse,
    ReleaseSourceResponse,
    ReleaseUpsertRequest,
)
from app.services.release_ledger import (
    ReleaseSourceConflictError,
    find_release_by_source,
    get_published_release,
    list_published_releases,
    upsert_release,
)

router = APIRouter(tags=["releases"])


async def require_release_writer_token(
    x_release_writer_token: Annotated[str | None, Header()] = None,
) -> None:
    """Require the server-only release-writer credential for mutation/reconciliation.

    Args:
        x_release_writer_token: Release-writer credential supplied by trusted automation.

    Returns:
        None.

    Raises:
        HTTPException: If release writing is unconfigured or the credential is invalid.
    """
    expected = os.getenv("RELEASE_WRITER_TOKEN", "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Release writer authorization is not configured",
        )
    if x_release_writer_token is None or not secrets.compare_digest(
        x_release_writer_token,
        expected,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid release writer credential",
        )


@router.get(
    "/source",
    response_model=ReleaseSourceResponse,
    description="Resolve whether trusted automation already published a GitHub source.",
)
async def reconcile_release_source(
    _: Annotated[None, Depends(require_release_writer_token)],
    db: AsyncSession = Depends(get_db),
    source_repository: str = Query(min_length=1, max_length=255),
    source_pr_number: int | None = Query(default=None, ge=1),
    source_merge_sha: str | None = Query(default=None, min_length=7, max_length=64),
) -> ReleaseSourceResponse:
    """Resolve whether trusted automation already published a GitHub source.

    Args:
        _: Successful release-writer authorization dependency.
        db: Async database session.
        source_repository: Repository containing the source pull request.
        source_pr_number: Source pull request number when known.
        source_merge_sha: Source merge commit SHA when known.

    Returns:
        Reconciliation result containing any matching durable release.

    Raises:
        HTTPException: If no source identity is supplied or the identities conflict.
    """
    if source_pr_number is None and source_merge_sha is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="source_pr_number or source_merge_sha is required",
        )
    try:
        release = await find_release_by_source(
            db,
            source_repository=source_repository,
            source_pr_number=source_pr_number,
            source_merge_sha=source_merge_sha,
        )
    except ReleaseSourceConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ReleaseSourceResponse(exists=release is not None, release=release)


@router.get(
    "/",
    response_model=ReleaseListResponse,
    description="List public published releases newest-first.",
)
async def list_releases(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ReleaseListResponse:
    """List public published releases newest-first.

    Args:
        db: Async database session.
        limit: Maximum releases to return.
        offset: Number of matching releases to skip.

    Returns:
        Paginated public release list and total count.
    """
    releases, total = await list_published_releases(db, limit=limit, offset=offset)
    return ReleaseListResponse(releases=releases, total=total, limit=limit, offset=offset)


@router.get(
    "/{release_id}",
    response_model=PublicReleaseResponse,
    description="Fetch one public published release.",
)
async def get_release(
    release_id: int,
    db: AsyncSession = Depends(get_db),
) -> PublicReleaseResponse:
    """Fetch one public published release.

    Args:
        release_id: Release primary key.
        db: Async database session.

    Returns:
        The requested public published release.

    Raises:
        HTTPException: If the release is unavailable to public readers.
    """
    release = await get_published_release(db, release_id)
    if release is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Release not found")
    return PublicReleaseResponse.model_validate(release)


@router.put(
    "/",
    response_model=ReleaseResponse,
    description="Idempotently create or update one merged-PR-backed release.",
)
async def publish_release(
    payload: ReleaseUpsertRequest,
    _: Annotated[None, Depends(require_release_writer_token)],
    db: AsyncSession = Depends(get_db),
) -> ReleaseResponse:
    """Idempotently create or update one merged-PR-backed release.

    Args:
        payload: Validated release publication request.
        _: Successful release-writer authorization dependency.
        db: Async database session.

    Returns:
        The created or updated durable release.

    Raises:
        HTTPException: If the source identity conflicts with established provenance.
    """
    try:
        release = await upsert_release(db, payload)
    except ReleaseSourceConflictError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ReleaseResponse.model_validate(release)


@router.post(
    "/{release_id}/retract",
    response_model=ReleaseResponse,
    description="Retract a release so it leaves the public What's New list.",
)
async def retract_release(
    release_id: int,
    _: Annotated[None, Depends(require_release_writer_token)],
    db: AsyncSession = Depends(get_db),
) -> ReleaseResponse:
    """Mark one release retracted so public readers no longer see it.

    Args:
        release_id: Release primary key.
        _: Successful release-writer authorization dependency.
        db: Async database session.

    Returns:
        The updated release with its status set to retracted.

    Raises:
        HTTPException: If no release exists with the given id.
    """
    release = await db.get(Release, release_id)
    if release is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Release not found")
    release.status = "retracted"
    await db.commit()
    await db.refresh(release)
    return ReleaseResponse.model_validate(release)

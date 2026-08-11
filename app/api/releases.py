"""Public read and service-authorized write API for What's New releases."""

import os
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.release import (
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
    """Require the server-only release-writer credential for mutation/reconciliation."""
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


@router.get("/source", response_model=ReleaseSourceResponse)
async def reconcile_release_source(
    _: Annotated[None, Depends(require_release_writer_token)],
    db: AsyncSession = Depends(get_db),
    source_repository: str = Query(min_length=1, max_length=255),
    source_pr_number: int | None = Query(default=None, ge=1),
    source_merge_sha: str | None = Query(default=None, min_length=7, max_length=64),
) -> ReleaseSourceResponse:
    """Resolve whether trusted automation already published a GitHub source."""
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


@router.get("/", response_model=ReleaseListResponse)
async def list_releases(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ReleaseListResponse:
    """List public published releases newest-first."""
    releases, total = await list_published_releases(db, limit=limit, offset=offset)
    return ReleaseListResponse(releases=releases, total=total, limit=limit, offset=offset)


@router.get("/{release_id}", response_model=ReleaseResponse)
async def get_release(
    release_id: int,
    db: AsyncSession = Depends(get_db),
) -> ReleaseResponse:
    """Fetch one public published release."""
    release = await get_published_release(db, release_id)
    if release is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Release not found")
    return ReleaseResponse.model_validate(release)


@router.put("/", response_model=ReleaseResponse)
async def publish_release(
    payload: ReleaseUpsertRequest,
    _: Annotated[None, Depends(require_release_writer_token)],
    db: AsyncSession = Depends(get_db),
) -> ReleaseResponse:
    """Idempotently create or update one merged-PR-backed release."""
    try:
        release = await upsert_release(db, payload)
    except ReleaseSourceConflictError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ReleaseResponse.model_validate(release)

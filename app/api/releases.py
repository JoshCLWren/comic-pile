"""Public read and service-authorized write API for What's New releases."""

import os
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.release import (
    PublicReleaseResponse,
    ReleaseListResponse,
    ReleaseResponse,
    ReleaseUpsertRequest,
)
from app.services.release_ledger import (
    ReleaseSourceConflictError,
    list_published_releases,
    public_release_payload,
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
    return ReleaseListResponse(
        releases=[
            PublicReleaseResponse.model_validate(public_release_payload(release))
            for release in releases
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


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



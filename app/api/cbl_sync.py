"""Service-authorized API for normalized CBL mirror synchronization."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.releases import require_release_writer_token
from app.cbl_ingest import CBLBook, CBLList
from app.cbl_remote_sync import finalize_cbl_sync, get_cbl_source_revision, sync_cbl_batch
from app.database import get_db
from app.schemas.cbl_sync import (
    CBLBatchRequest,
    CBLBatchResponse,
    CBLFinalizeRequest,
    CBLSourceStatusResponse,
)

router = APIRouter(prefix="/cbl-sync", tags=["cbl-sync"])


@router.get("/source", response_model=CBLSourceStatusResponse)
async def get_source_status(
    _: Annotated[None, Depends(require_release_writer_token)],
    repository: str = Query(min_length=1, max_length=255),
    db: AsyncSession = Depends(get_db),
) -> CBLSourceStatusResponse:
    """Return the last completely synchronized revision for one repository.

    Args:
        _: Successful trusted-automation authorization dependency.
        repository: Stable source repository identity.
        db: Application database session.

    Returns:
        Source identity and the last fully published revision SHA.
    """
    revision_sha = await get_cbl_source_revision(db, repository=repository)
    return CBLSourceStatusResponse(repository=repository, revision_sha=revision_sha)


@router.post("/batch", response_model=CBLBatchResponse)
async def import_batch(
    payload: CBLBatchRequest,
    _: Annotated[None, Depends(require_release_writer_token)],
    db: AsyncSession = Depends(get_db),
) -> CBLBatchResponse:
    """Persist one bounded batch without declaring the revision complete.

    Args:
        payload: Repository, revision, and normalized CBL lists for this batch.
        _: Successful trusted-automation authorization dependency.
        db: Application database session.

    Returns:
        Counters describing the persisted batch.

    Raises:
        HTTPException: If the batch contains invalid source metadata.
    """
    parsed = tuple(
        CBLList(
            source_path=item.source_path,
            content_hash=item.content_hash,
            name=item.name,
            declared_issue_count=item.declared_issue_count,
            books=tuple(CBLBook(**book.model_dump()) for book in item.books),
        )
        for item in payload.lists
    )
    try:
        summary = await sync_cbl_batch(
            db,
            repository=payload.repository,
            revision_sha=payload.revision_sha,
            parsed_lists=parsed,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return CBLBatchResponse(**asdict(summary))


@router.post("/finalize", response_model=CBLBatchResponse)
async def finalize_sync(
    payload: CBLFinalizeRequest,
    _: Annotated[None, Depends(require_release_writer_token)],
    db: AsyncSession = Depends(get_db),
) -> CBLBatchResponse:
    """Mark missing lists inactive and atomically publish the completed revision.

    Args:
        payload: Repository, revision, complete active path set, and protected paths.
        _: Successful trusted-automation authorization dependency.
        db: Application database session.

    Returns:
        Counters describing finalization and deactivation work.

    Raises:
        HTTPException: If finalization metadata is invalid or the source is missing.
    """
    try:
        summary = await finalize_cbl_sync(
            db,
            repository=payload.repository,
            revision_sha=payload.revision_sha,
            active_paths=frozenset(payload.active_paths),
            protected_paths=frozenset(payload.protected_paths),
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return CBLBatchResponse(**asdict(summary))

"""API endpoints for reading plan sync service."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.reading_plan_sync_service import sync_released_issues, SyncResult

router = APIRouter()


class SyncRequest(BaseModel):
    """Request for sync operation."""
    as_of: datetime = Field(
        description="UTC timestamp defining the release boundary - only issues with "
                   "store_date <= as_of will be adopted"
    )
    refresh: bool = Field(
        default=True,
        description="Whether to refresh the ComicVine cache"
    )


class SyncResponse(BaseModel):
    """Response from sync operation."""
    success: bool
    message: str
    result: SyncResult


@router.post("/sync", response_model=SyncResponse)
async def sync_released_issues_endpoint(
    request: SyncRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Synchronize followed ComicVine volumes and adopt only released issues.

    This endpoint processes all enabled release sources for the current user,
    fetching ComicVine volume issues and adopting only those that have been
    released (store_date <= as_of).
    """
    try:
        # Perform the sync
        result = await sync_released_issues(
            db=db,
            as_of=request.as_of,
            refresh=request.refresh,
        )

        # Convert SyncResult to dict for serialization
        result_dict = {
            "total_sources": result.total_sources,
            "enabled_sources": result.enabled_sources,
            "successful_sources": result.successful_sources,
            "failed_sources": result.failed_sources,
            "created_issues": result.created_issues,
            "reused_issues": result.reused_issues,
            "future_skips": result.future_skips,
            "unknown_date_skips": result.unknown_date_skips,
            "conflicts": result.conflicts,
            "errors": result.errors,
        }

        return SyncResponse(
            success=result.failed_sources == 0,
            message=f"Sync completed: {result.successful_sources} successful, "
                   f"{result.failed_sources} failed, "
                   f"{result.created_issues} created, "
                   f"{result.reused_issues} reused",
            result=result_dict,
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Sync failed: {str(e)}",
        ) from e


@router.get("/status")
async def get_sync_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get sync status for the current user's enabled release sources.

    Returns information about enabled sources and their last sync status.
    """
    try:
        from app.repositories.reading_plan_release_source_repository import (
            get_enabled_sources_by_user,
        )

        # Get all enabled sources for the current user
        enabled_sources = await get_enabled_sources_by_user(db, current_user.id)

        # Prepare status information
        status_info = {
            "total_enabled_sources": len(enabled_sources),
            "sources": [],
        }

        for source in enabled_sources:
            status_info["sources"].append({
                "id": source.id,
                "reading_plan_id": source.plan_id,
                "thread_id": source.thread_id,
                "volume_id": int(source.external_identity.external_id),
                "enabled": source.enabled,
                "last_synced_at": source.last_synced_at,
                "created_at": source.created_at,
                "updated_at": source.updated_at,
            })

        return status_info

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get sync status: {str(e)}",
        ) from e
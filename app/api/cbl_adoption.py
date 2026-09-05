"""API endpoints for CBL adoption preview, planning, and commitment."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.cbl_adoption import (
    preview_cbl_source_list,
    calculate_cbl_adoption_plan,
    commit_cbl_adoption_plan,
)
from app.schemas.cbl_adoption import (
    CBLPreviewResponse,
    CBLPlanCalculationRequest,
    CBLPlanCalculationResponse,
)

router = APIRouter(prefix="/api/v1/cbl-lists", tags=["cbl-adoption"])


@router.get(
    "/{list_id}/preview",
    response_model=CBLPreviewResponse,
    status_code=status.HTTP_200_OK,
)
async def preview_cbl_source_list_endpoint(
    list_id: int = Path(..., ge=1, description="CBL source list ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CBLPreviewResponse:
    """Get a preview of a CBL source list for the current user.
    
    Returns a read-only preview showing all source positions with resolution status,
    read status, and other contextual information. Does not mutate any data.
    """
    return await preview_cbl_source_list(
        db,
        user_id=current_user.id,
        list_id=list_id,
    )


@router.post(
    "/{list_id}/calculate-plan",
    response_model=CBLPlanCalculationResponse,
    status_code=status.HTTP_200_OK,
)
async def calculate_cbl_adoption_plan_endpoint(
    list_id: int = Path(..., ge=1, description="CBL source list ID"),
    request: CBLPlanCalculationRequest = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CBLPlanCalculationResponse:
    """Calculate an adoption plan for a CBL source list based on reader decisions.
    
    Returns a dry-run summary of what would happen if the plan were committed,
    including which issues would be reused, which would be created, and the
    resulting source-backed order. Does not mutate any data.
    """
    if request is None:
        request = CBLPlanCalculationRequest()
    
    # Convert the request format to the format expected by the service
    series_decisions = {
        sd.series_name: sd.decision for sd in request.series_decisions
    } if request.series_decisions else None

    entry_decisions = dict(request.entry_decisions) if request.entry_decisions else None

    return await calculate_cbl_adoption_plan(
        db,
        user_id=current_user.id,
        list_id=list_id,
        series_decisions=series_decisions,
        entry_decisions=entry_decisions,
    )


@router.post(
    "/{list_id}/commit",
    status_code=status.HTTP_200_OK,
)
async def commit_cbl_adoption_plan_endpoint(
    list_id: int = Path(..., ge=1, description="CBL source list ID"),
    request: CBLPlanCalculationRequest = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Commit an adoption plan for a CBL source list.
    
    Applies the reader-approved mutations: creates missing issues, reuses existing
    issues, and persists the source-backed order using the canonical ordered
    membership representation. Refreshes denormalized blocked state after commit.
    """
    if request is None:
        request = CBLPlanCalculationRequest()
    
    # Convert the request format to the format expected by the service
    series_decisions = {
        sd.series_name: sd.decision for sd in request.series_decisions
    } if request.series_decisions else None

    entry_decisions = dict(request.entry_decisions) if request.entry_decisions else None

    return await commit_cbl_adoption_plan(
        db,
        user_id=current_user.id,
        list_id=list_id,
        series_decisions=series_decisions,
        entry_decisions=entry_decisions,
    )


# Export the router
__all__ = ["router"]
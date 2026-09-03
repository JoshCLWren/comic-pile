"""Read-only preview and adoption-plan API for CBL source lists.

This module provides the backend services and routes for reading and calculating
decisions on CBL source lists without creating or mutating user-owned reading state.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.cbl_adoption import (
    CBLMutationSummary,
    CBLPreviewResponse,
    CBLAdoptionPlanRequest,
)
from app.services.cbl_adoption import (
    preview_cbl_source_list as _preview_cbl_source_list,
    calculate_adoption_plan as _calculate_adoption_plan,
)

router = APIRouter(prefix="/api/v1/cbl-adoption", tags=["cbl-adoption"])


@router.get("/{list_id}/preview", response_model=CBLPreviewResponse)
async def api_preview_cbl_source_list(
    list_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> CBLPreviewResponse:
    """Get a read-only preview of one CBL source list for the current user.

    Returns the full preview including per-entry state (existing canonical issue
    with read status, missing/importable, ambiguous) and source metadata.

    Args:
        list_id: CBLSourceList identifier.
        current_user: Authenticated owner.
        db: Async database session.

    Returns:
        Structured preview response.

    Raises:
        HTTPException: If the source list does not exist or is not active.
    """
    return await _preview_cbl_source_list(db, user_id=current_user.id, list_id=list_id)


@router.post("/{list_id}/plan", response_model=CBLMutationSummary)
async def api_calculate_adoption_plan(
    list_id: int,
    request: CBLAdoptionPlanRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> CBLMutationSummary:
    """Calculate the adoption-plan summary for one CBL source list.

    Applies the proposed decisions to the preview and returns a read-only
    mutation summary without creating or mutating any state.

    Args:
        list_id: CBLSourceList identifier.
        request: Adoption decisions to apply.
        current_user: Authenticated owner.
        db: Async database session.

    Returns:
        Read-only mutation summary.

    Raises:
        HTTPException: If the source list does not exist or is not active.
    """
    return await _calculate_adoption_plan(
        db, user_id=current_user.id, list_id=list_id, decisions=request.decisions
    )

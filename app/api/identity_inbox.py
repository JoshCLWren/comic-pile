"""API routes for the identity reconciliation inbox."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.external_identities import ExternalIdentityMappingError
from app.models.user import User
from app.schemas.identity_inbox import (
    IdentityInboxActionRequest,
    IdentityInboxActionResponse,
    IdentityInboxResponse,
)
from app.services.identity_inbox import (
    confirm_inbox_candidate,
    defer_inbox_item,
    get_inbox_item,
    list_inbox_items,
    reject_inbox_candidate,
    skip_inbox_item,
)

router = APIRouter(prefix="/api/v1/identity-inbox", tags=["identity-inbox"])


@router.get(
    "",
    response_model=IdentityInboxResponse,
)
async def api_list_inbox(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=100, description="Maximum items to return"),
) -> IdentityInboxResponse:
    """List unresolved or ambiguous external identity mappings for the current user.

    Args:
        current_user: Authenticated owner.
        db: Async database session.
        offset: Pagination offset.
        limit: Maximum items to return.

    Returns:
        Paginated list of inbox items.
    """
    items, total = await list_inbox_items(
        db, user_id=current_user.id, offset=offset, limit=limit
    )
    return IdentityInboxResponse(
        items=items, total=total, offset=offset, limit=limit
    )


@router.get(
    "/{mapping_id}",
    response_model=IdentityInboxResponse,
)
async def api_get_inbox_item(
    mapping_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> IdentityInboxResponse:
    """Get a single inbox item with all its candidates.

    Args:
        mapping_id: The mapping ID to retrieve.
        current_user: Authenticated owner.
        db: Async database session.

    Returns:
        Single-item response with candidates.
    """
    item = await get_inbox_item(db, user_id=current_user.id, mapping_id=mapping_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inbox item {mapping_id} not found",
        )
    return IdentityInboxResponse(items=[item], total=1, offset=0, limit=1)


@router.post(
    "/{mapping_id}/confirm",
    response_model=IdentityInboxActionResponse,
)
async def api_confirm_candidate(
    mapping_id: int,
    request: IdentityInboxActionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> IdentityInboxActionResponse:
    """Confirm a candidate for an unresolved identity mapping."""
    if request.external_identity_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="external_identity_id is required for confirm action",
        )
    try:
        result = await confirm_inbox_candidate(
            db,
            user_id=current_user.id,
            mapping_id=mapping_id,
            external_identity_id=request.external_identity_id,
        )
        await db.commit()
        return result
    except ExternalIdentityMappingError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post(
    "/{mapping_id}/reject",
    response_model=IdentityInboxActionResponse,
)
async def api_reject_candidate(
    mapping_id: int,
    request: IdentityInboxActionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> IdentityInboxActionResponse:
    """Reject a candidate for an identity mapping."""
    if request.external_identity_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="external_identity_id is required for reject action",
        )
    if not request.rejection_reason or not request.rejection_reason.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="rejection_reason is required when rejecting a candidate",
        )
    try:
        result = await reject_inbox_candidate(
            db,
            user_id=current_user.id,
            mapping_id=mapping_id,
            external_identity_id=request.external_identity_id,
            rejection_reason=request.rejection_reason,
        )
        await db.commit()
        return result
    except ExternalIdentityMappingError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post(
    "/{mapping_id}/defer",
    response_model=IdentityInboxActionResponse,
)
async def api_defer_item(
    mapping_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> IdentityInboxActionResponse:
    """Defer a mapping for later review."""
    try:
        result = await defer_inbox_item(
            db, user_id=current_user.id, mapping_id=mapping_id
        )
        await db.commit()
        return result
    except ExternalIdentityMappingError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post(
    "/{mapping_id}/skip",
    response_model=IdentityInboxActionResponse,
)
async def api_skip_item(
    mapping_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> IdentityInboxActionResponse:
    """Skip an inbox item for the current adoption workflow."""
    try:
        result = await skip_inbox_item(
            db, user_id=current_user.id, mapping_id=mapping_id
        )
        await db.commit()
        return result
    except ExternalIdentityMappingError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

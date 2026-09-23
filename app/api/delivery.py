"""Cross-repository delivery API endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.delivery import DeliveryRecord as DeliveryRecordModel
from app.schemas.delivery import (
    CrossRepoDeliveryRequest,
    DeliveryRecordCreate,
    DeliveryRecordResponse,
    DeliveryResult,
)
from app.services.delivery import DeliveryService

router = APIRouter()


@router.post("/delivery", response_model=DeliveryResult)
async def create_delivery_request(
    request: CrossRepoDeliveryRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(get_current_user)],
    delivery_service: Annotated[DeliveryService, Depends()],
) -> DeliveryResult:
    """Create a cross-repository delivery request.
    
    This endpoint allows the factory to deliver extracted code to target
    repositories. The delivery service handles:
    - Target repository validation
    - Credential management (GITHUB_TOKEN vs LATTICERY_TOKEN)
    - Branch creation on target repository
    - PR creation on target repository
    - Delivery ledger tracking
    
    Args:
        request: The cross-repository delivery request containing:
            - target_repository: Target repository (JoshCLWren/comic-pile or JoshCLWren/Latticery)
            - branch_name: Name of branch to create
            - base_branch: Base branch for the PR
            - title: PR title
            - body: PR body (optional)
            - issue_number: Linked issue number (optional)
            - worker_id: Factory worker ID
        db: Async database session
        current_user: Authenticated user
        delivery_service: Delivery service instance
        
    Returns:
        DeliveryResult with operation outcome and tracking information
        
    Raises:
        HTTPException: For invalid target repositories or delivery failures
    """
    try:
        result = await delivery_service.deliver_to_target(db, request)
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/delivery", response_model=list[DeliveryRecordResponse])
async def list_delivery_records(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(get_current_user)],
) -> list[DeliveryRecordResponse]:
    """List all delivery records.
    
    Args:
        db: Async database session
        current_user: Authenticated user
        
    Returns:
        List of delivery records
    """
    result = await db.execute(select(DeliveryRecordModel))
    records = result.scalars().all()
    return [DeliveryRecordResponse.model_validate(record) for record in records]


@router.get("/delivery/{delivery_id}", response_model=DeliveryRecordResponse)
async def get_delivery_record(
    delivery_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(get_current_user)],
) -> DeliveryRecordResponse:
    """Get a specific delivery record by ID.
    
    Args:
        delivery_id: Delivery record ID
        db: Async database session
        current_user: Authenticated user
        
    Returns:
        Delivery record details
        
    Raises:
        HTTPException: If delivery record not found
    """
    result = await db.execute(
        select(DeliveryRecordModel).where(DeliveryRecordModel.id == delivery_id)
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Delivery record {delivery_id} not found",
        )
    return DeliveryRecordResponse.model_validate(record)


@router.get("/delivery/target/{target_repository}/branch/{branch_name}", response_model=DeliveryRecordResponse)
async def get_delivery_by_target_branch(
    target_repository: str,
    branch_name: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(get_current_user)],
) -> DeliveryRecordResponse:
    """Get delivery record by target repository and branch name.
    
    Args:
        target_repository: Target repository name
        branch_name: Target branch name
        db: Async database session
        current_user: Authenticated user
        
    Returns:
        Delivery record details
        
    Raises:
        HTTPException: If delivery record not found
    """
    result = await db.execute(
        select(DeliveryRecordModel).where(
            DeliveryRecordModel.target_repository == target_repository,
            DeliveryRecordModel.target_branch == branch_name,
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Delivery record for {target_repository} branch {branch_name} not found",
        )
    return DeliveryRecordResponse.model_validate(record)


@router.patch("/delivery/{delivery_id}", response_model=DeliveryRecordResponse)
async def update_delivery_record(
    delivery_id: int,
    update_data: DeliveryRecordCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(get_current_user)],
    delivery_service: Annotated[DeliveryService, Depends()],
) -> DeliveryRecordResponse:
    """Update a delivery record.
    
    Args:
        delivery_id: Delivery record ID
        update_data: Fields to update
        db: Async database session
        current_user: Authenticated user
        delivery_service: Delivery service instance
        
    Returns:
        Updated delivery record
        
    Raises:
        HTTPException: If delivery record not found
    """
    record = await delivery_service.update_delivery_record(db, delivery_id, update_data)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Delivery record {delivery_id} not found",
        )
    return DeliveryRecordResponse.model_validate(record)
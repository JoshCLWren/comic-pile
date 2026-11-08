"""Roll API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.roll_service import RollService
from app.schemas import (
    OverrideRequest,
    RollResponse,
)

router = APIRouter(tags=["roll"])
legacy_router = APIRouter(tags=["roll"])


@legacy_router.post("/dismiss-pending", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_pending_roll_legacy(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> None:
    """Clear any pending thread (legacy unversioned alias, shadowed by Rust).

    Args:
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.
    """
    service = RollService(db)
    await service.execute_dismiss_pending(current_user.id)


@router.post("/dismiss-pending", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_pending_roll(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> None:
    """Clear any pending thread for the current session.

    Args:
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.
    """
    service = RollService(db)
    await service.execute_dismiss_pending(current_user.id)


@router.post("/override", response_model=RollResponse)
async def override_roll(
    request: OverrideRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> RollResponse:
    """Manually select a thread.

    Args:
        request: Override request containing thread_id.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        RollResponse with selected thread.

    Raises:
        HTTPException: If thread not found.
    """
    return await RollService(db).execute_override(
        thread_id=request.thread_id, current_user=current_user
    )



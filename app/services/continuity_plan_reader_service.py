"""Continuity plan reader service."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.continuity_plan_reader import ContinuityPlanReaderResponse


async def get_continuity_plan_reader(
    db: AsyncSession, *, user_id: int, plan_id: int,
) -> ContinuityPlanReaderResponse:
    """Return Option E plan projected from its authoritative Reading List.

    Args:
        db: Request transaction.
        user_id: Authenticated owner; ownership is checked before graph loading.
        plan_id: Continuity plan ID; must be owned by the authenticated user.

    Returns:
        Option E plan projected from its authoritative Reading List.

    Raises:
        HTTPException: 404 if the plan is not found or not owned by the user.
        HTTPException: 409 if the plan has no linked authoritative Reading List.
    """
    # TODO: Implement the actual service logic that calls the native Rust API
    # For now, return a placeholder response
    raise NotImplementedError("Continuity plan reader service not yet implemented")
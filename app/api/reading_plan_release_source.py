"""CRUD API for Reading Plan release sources."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.reading_plan_release_source import (
    ReleaseSourceCreate,
    ReleaseSourceResponse,
    ReleaseSourceUpdate,
)
from app.services import reading_plan_release_source_service as service

router = APIRouter(tags=["reading-plan-release-sources"])


@router.post(
    "/continuity-plans/release-sources/",
    response_model=ReleaseSourceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_release_source(
    payload: ReleaseSourceCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReleaseSourceResponse:
    """Subscribe a plan+thread to a confirmed ComicVine volume."""
    return await service.create_source(db, data=payload, user_id=current_user.id)


@router.get(
    "/continuity-plans/{plan_id}/release-sources/",
    response_model=list[ReleaseSourceResponse],
)
async def list_release_sources(
    plan_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ReleaseSourceResponse]:
    """List release sources for one plan."""
    return await service.list_sources(db, plan_id=plan_id, user_id=current_user.id)


@router.patch(
    "/continuity-plans/release-sources/{source_id}",
    response_model=ReleaseSourceResponse,
)
async def update_release_source(
    source_id: int,
    payload: ReleaseSourceUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReleaseSourceResponse:
    """Enable or disable a release source (non-destructive)."""
    return await service.update_source(
        db, source_id=source_id, data=payload, user_id=current_user.id
    )


@router.delete(
    "/continuity-plans/release-sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_release_source(
    source_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Remove a release source subscription."""
    await service.delete_source(db, source_id=source_id, user_id=current_user.id)

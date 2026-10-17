"""Owner-scoped stable prerequisites; historical provenance is read-only."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.prerequisite import (
    PrerequisiteCreate,
    PrerequisiteNoteUpdate,
    PrerequisiteResponse,
)
from app.services import prerequisite_service as service

router = APIRouter(prefix="/prerequisites", tags=["prerequisites"])


@contextmanager
def _map_errors() -> Iterator[None]:
    """Translate service failures without exposing another reader's data."""
    try:
        yield
    except service.PrerequisiteNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except service.HistoricalPrerequisiteError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/", response_model=list[PrerequisiteResponse])
async def list_prerequisites(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> list[PrerequisiteResponse]:
    """Read stable endpoints and their unmodified provenance."""
    return await service.list_owned(db, current_user.id)


@router.post("/", response_model=PrerequisiteResponse, status_code=201)
async def create_prerequisite(
    data: PrerequisiteCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> PrerequisiteResponse:
    """Create one explicit reader prerequisite after combined cycle validation."""
    with _map_errors():
        return await service.create(db, current_user.id, data)


@router.patch("/{prerequisite_id}", response_model=PrerequisiteResponse)
async def update_prerequisite_note(
    prerequisite_id: int,
    data: PrerequisiteNoteUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> PrerequisiteResponse:
    """Edit the note of a new reader-authored requirement."""
    with _map_errors():
        return await service.update_note(db, current_user.id, prerequisite_id, data.note)


@router.delete("/{prerequisite_id}", status_code=204)
async def delete_prerequisite(
    prerequisite_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a reader requirement without changing read state or list intent."""
    with _map_errors():
        await service.delete(db, current_user.id, prerequisite_id)

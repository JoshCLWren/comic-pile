"""Owner-scoped collection exclusion API, inactive until Option E cutover."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.collection_exclusion import (
    CollectionExclusionCreate,
    CollectionExclusionResponse,
)
from app.services import collection_exclusion_service as service
from app.services.errors import InvalidRequestError, NotFoundError

router = APIRouter(prefix="/collection-exclusions", tags=["collection-exclusions"])


@router.get("", response_model=list[CollectionExclusionResponse])
async def list_exclusions(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[CollectionExclusionResponse]:
    """Return exclusions explicitly entered by this reader."""
    rows = await service.list_collection_exclusions(db, user_id=current_user.id)
    return [CollectionExclusionResponse.model_validate(row) for row in rows]


@router.post("", response_model=CollectionExclusionResponse)
async def create_exclusion(
    payload: CollectionExclusionCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CollectionExclusionResponse:
    """Idempotently exclude one external volume, Thread or Issue."""
    try:
        row = await service.create_collection_exclusion(
            db, user_id=current_user.id, payload=payload
        )
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except InvalidRequestError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return CollectionExclusionResponse.model_validate(row)


@router.delete("/{exclusion_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_exclusion(
    exclusion_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Remove one owned exclusion without changing the underlying comic."""
    try:
        await service.delete_collection_exclusion(
            db, user_id=current_user.id, exclusion_id=exclusion_id
        )
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except InvalidRequestError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)

"""Batched crossover membership reads for thread-oriented screens."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.dependency_group import DependencyGroupSummary
from app.services import dependency_group_service
from app.services.errors import ServiceError

router = APIRouter()

MAX_BATCH_THREADS = 200


class DependencyGroupThreadBatchRequest(BaseModel):
    """Request crossover summaries for a bounded set of owned threads."""

    thread_ids: list[int] = Field(min_length=1, max_length=MAX_BATCH_THREADS)


_ERROR_STATUS: dict[type[ServiceError], int] = {
    ServiceError: status.HTTP_404_NOT_FOUND,
}


def _map_service_error(exc: ServiceError) -> HTTPException:
    """Translate a domain error into its HTTP equivalent."""
    return HTTPException(
        status_code=_ERROR_STATUS[type(exc)], detail=exc.detail
    )


@router.post(
    "/threads/groups:batch",
    response_model=dict[int, list[DependencyGroupSummary]],
    description="List crossover groups for several owned threads in one request.",
)
async def list_thread_groups_batch(
    payload: DependencyGroupThreadBatchRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict[int, list[DependencyGroupSummary]]:
    """Return distinct crossover summaries for each requested owned thread.

    Args:
        payload: The bounded thread identifiers to resolve.
        current_user: The authenticated owner of the requested threads and groups.
        db: The asynchronous database session.

    Returns:
        A mapping from thread ID to zero or more crossover summaries.

    Raises:
        HTTPException: If any requested thread is not owned by the current user.
    """
    try:
        return await dependency_group_service.DependencyGroupService(
            db
        ).list_thread_groups_batch(current_user.id, payload.thread_ids)
    except ServiceError as exc:
        raise _map_service_error(exc) from exc

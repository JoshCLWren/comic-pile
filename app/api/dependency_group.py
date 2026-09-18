"""Authenticated API for user-owned named dependency groups.

Thin routing layer: authentication, request/response schema validation, HTTP
status mapping, and rate limiting. Business rules, orchestration, transaction
boundaries, and cache invalidation live in
``app/services/dependency_group_service.py``; persistence lives in
``app/repositories/dependency_group_repository.py``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.dependency_group import (
    DependencyGroupCreate,
    DependencyGroupDetailResponse,
    DependencyGroupIssueRangeCreate,
    DependencyGroupIssueRangeResponse,
    DependencyGroupMemberCreate,
    DependencyGroupMemberResponse,
    DependencyGroupOrderUpdate,
    DependencyGroupResponse,
    DependencyGroupSummary,
    DependencyGroupUpdate,
)
from app.services.dependency_group_service import DependencyGroupService
from app.services.errors import ConflictError, InvalidRequestError, NotFoundError, ServiceError

router = APIRouter(prefix="/reading-order-groups", tags=["reading-order-groups"])

_ERROR_STATUS: dict[type[ServiceError], int] = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
    InvalidRequestError: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ConflictError: status.HTTP_409_CONFLICT,
}


def _map_service_error(exc: ServiceError) -> HTTPException:
    """Translate a domain error into its HTTP equivalent.

    Args:
        exc: Domain error raised by a dependency-group service method.

    Returns:
        HTTPException carrying the mapped status code and client-safe detail.
    """
    return HTTPException(status_code=_ERROR_STATUS[type(exc)], detail=exc.detail)


@router.get(
    "/",
    response_model=list[DependencyGroupResponse],
    description="List the current user's groups and memberships.",
)
async def list_groups(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> list[DependencyGroupResponse]:
    """List the current user's groups and memberships.

    Args:
        current_user: The authenticated owner of the requested groups.
        db: The asynchronous database session.

    Returns:
        The user's groups with memberships resolved to comic metadata.
    """
    try:
        return await DependencyGroupService(db).list_groups(current_user.id)
    except ServiceError as exc:
        raise _map_service_error(exc) from exc


@router.post(
    "/",
    response_model=DependencyGroupResponse,
    status_code=201,
    description="Create a user-owned named group.",
)
async def create_group(
    payload: DependencyGroupCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> DependencyGroupResponse:
    """Create a named dependency group.

    Args:
        payload: The validated group creation request.
        current_user: The authenticated group owner.
        db: The asynchronous database session.

    Returns:
        The newly created group with memberships loaded.
    """
    try:
        return await DependencyGroupService(db).create_group(current_user.id, payload)
    except ServiceError as exc:
        raise _map_service_error(exc) from exc


@router.get(
    "/threads/{thread_id}/groups",
    response_model=list[DependencyGroupSummary],
    description="List groups containing an owned thread or any of its owned issues.",
)
async def list_thread_groups(
    thread_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> list[DependencyGroupSummary]:
    """List groups containing an owned thread or any of its owned issues.

    Args:
        thread_id: The owned thread identifier used for the lookup.
        current_user: The authenticated thread and group owner.
        db: The asynchronous database session.

    Returns:
        Distinct group summaries ordered by name and identifier.
    """
    try:
        return await DependencyGroupService(db).list_thread_groups(current_user.id, thread_id)
    except ServiceError as exc:
        raise _map_service_error(exc) from exc


@router.get(
    "/{group_id}",
    response_model=DependencyGroupResponse,
    description="Return one owned group.",
)
async def get_group(
    group_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> DependencyGroupResponse:
    """Return one owned group.

    Args:
        group_id: The dependency group identifier.
        current_user: The authenticated group owner.
        db: The asynchronous database session.

    Returns:
        The requested owned group with memberships resolved to comic metadata.
    """
    try:
        return await DependencyGroupService(db).get_group(current_user.id, group_id)
    except ServiceError as exc:
        raise _map_service_error(exc) from exc


@router.get(
    "/{group_id}/detail",
    response_model=DependencyGroupDetailResponse,
    description="Return one owned group with enriched member, plan, and project data.",
)
async def get_group_detail(
    group_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> DependencyGroupDetailResponse:
    """Return one owned group with enriched detail for crossover view.

    Args:
        group_id: The dependency group identifier.
        current_user: The authenticated group owner.
        db: The asynchronous database session.

    Returns:
        The requested owned group with enriched member, plan, and project
        data, avoiding per-member N+1 requests.
    """
    try:
        return await DependencyGroupService(db).get_group_detail(current_user.id, group_id)
    except ServiceError as exc:
        raise _map_service_error(exc) from exc


@router.patch(
    "/{group_id}",
    response_model=DependencyGroupResponse,
    description="Rename one owned group.",
)
async def update_group(
    group_id: int,
    payload: DependencyGroupUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> DependencyGroupResponse:
    """Rename one owned group.

    Args:
        group_id: The dependency group identifier.
        payload: The validated group rename request.
        current_user: The authenticated group owner.
        db: The asynchronous database session.

    Returns:
        The renamed group with memberships resolved to comic metadata.
    """
    try:
        return await DependencyGroupService(db).update_group(current_user.id, group_id, payload)
    except ServiceError as exc:
        raise _map_service_error(exc) from exc


@router.delete(
    "/{group_id}",
    status_code=204,
    description="Delete one owned group and its memberships.",
)
async def delete_group(
    group_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete one owned group and its memberships.

    Args:
        group_id: The dependency group identifier.
        current_user: The authenticated group owner.
        db: The asynchronous database session.

    Returns:
        An empty HTTP 204 response.
    """
    try:
        await DependencyGroupService(db).delete_group(current_user.id, group_id)
    except ServiceError as exc:
        raise _map_service_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{group_id}/issue-ranges",
    response_model=DependencyGroupIssueRangeResponse,
    status_code=200,
    description="Add one inclusive issue-position range from an owned thread to a group.",
)
async def add_issue_range(
    group_id: int,
    payload: DependencyGroupIssueRangeCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> DependencyGroupIssueRangeResponse:
    """Add one inclusive issue-position range from an owned thread to a group.

    Args:
        group_id: The dependency group identifier.
        payload: The validated issue-position range request.
        current_user: The authenticated group and thread owner.
        db: The asynchronous database session.

    Returns:
        The idempotent range result with inserted and already-present issue IDs.
    """
    try:
        return await DependencyGroupService(db).add_issue_range(current_user.id, group_id, payload)
    except ServiceError as exc:
        raise _map_service_error(exc) from exc


@router.post(
    "/{group_id}/members",
    response_model=DependencyGroupMemberResponse,
    status_code=201,
    description="Add one owned thread or issue to an owned group.",
)
async def add_member(
    group_id: int,
    payload: DependencyGroupMemberCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> DependencyGroupMemberResponse:
    """Add one owned thread or issue to an owned group.

    Args:
        group_id: The dependency group identifier.
        payload: The validated thread or issue membership request.
        current_user: The authenticated owner of the group and target.
        db: The asynchronous database session.

    Returns:
        The newly persisted membership with resolved comic metadata.
    """
    try:
        return await DependencyGroupService(db).add_member(current_user.id, group_id, payload)
    except ServiceError as exc:
        raise _map_service_error(exc) from exc


@router.put(
    "/{group_id}/order",
    response_model=DependencyGroupResponse,
    description=(
        "Set the authoritative ordered reading sequence of a crossover's issue-level members."
    ),
)
async def set_group_order(
    group_id: int,
    payload: DependencyGroupOrderUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> DependencyGroupResponse:
    """Replace the authoritative reading order of one owned crossover.

    The payload enumerates issue-level members in their intended reading order;
    each listed issue's ``sequence_order`` is persisted verbatim (the provided
    order is the canonical source, never re-derived from membership ids or
    per-series issue positions). Any issue-level member not listed is cleared to
    unordered. Thread-level memberships are never sequence entries and are left
    untouched.

    Args:
        group_id: The dependency group identifier.
        payload: The ordered issue list for the crossover.
        current_user: The authenticated owner of the group and referenced issues.
        db: The asynchronous database session.

    Returns:
        The updated group with memberships resolved to comic metadata.
    """
    try:
        return await DependencyGroupService(db).set_group_order(current_user.id, group_id, payload)
    except ServiceError as exc:
        raise _map_service_error(exc) from exc


@router.get(
    "/{group_id}/plans",
    response_model=list[DependencyGroupSummary],
    description="List continuity plans that reference this crossover as a node.",
)
async def list_crossover_plans(
    group_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> list[DependencyGroupSummary]:
    """List continuity plans containing this crossover as a node.

    Args:
        group_id: The dependency group identifier.
        current_user: The authenticated group and plan owner.
        db: The asynchronous database session.

    Returns:
        Distinct plan summaries ordered by name and identifier.
    """
    try:
        return await DependencyGroupService(db).list_crossover_plans(current_user.id, group_id)
    except ServiceError as exc:
        raise _map_service_error(exc) from exc


@router.delete(
    "/{group_id}/members/{member_id}",
    status_code=204,
    description="Remove one membership from an owned group.",
)
async def remove_member(
    group_id: int,
    member_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Remove one membership from an owned group.

    Args:
        group_id: The dependency group identifier.
        member_id: The membership identifier to remove.
        current_user: The authenticated group owner.
        db: The asynchronous database session.

    Returns:
        An empty HTTP 204 response.
    """
    try:
        await DependencyGroupService(db).remove_member(current_user.id, group_id, member_id)
    except ServiceError as exc:
        raise _map_service_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)

"""Dependency API endpoints (/api/v1)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.dependency import (
    BatchBlockingExplanationRequest,
    BatchBlockingExplanationResponse,
    BlockingExplanation,
    DependencyCreate,
    DependencyNoteUpdate,
    DependencyOrderConflict,
    DependencyOrderRequirement,
    DependencyResponse,
    IssueDependenciesResponse,
    ThreadConnectedResponse,
    ThreadDependencyOrderCheckResponse,
    ThreadDependenciesResponse,
)
from app.services import dependency_service


router = APIRouter(tags=["dependencies"])


@router.get("/dependencies/blocked", response_model=list[int])
async def get_all_blocked_thread_ids(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> list[int]:
    """Return all currently blocked thread IDs for the current user."""
    return await dependency_service.get_all_blocked_thread_ids(current_user.id, db)


@router.get("/threads/{thread_id}/dependencies", response_model=ThreadDependenciesResponse)
async def list_thread_dependencies(
    thread_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ThreadDependenciesResponse:
    """List dependencies where a thread blocks others and where it is blocked."""
    result = await dependency_service.get_thread_dependencies(thread_id, current_user.id, db)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )
    return result


@router.get("/issues/{issue_id}/dependencies", response_model=IssueDependenciesResponse)
async def list_issue_dependencies(
    issue_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> IssueDependenciesResponse:
    """List all incoming and outgoing dependency edges for a specific issue."""
    result = await dependency_service.get_issue_dependencies(issue_id, current_user.id, db)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Issue {issue_id} not found",
        )
    return result


@router.post("/threads/{thread_id}:getBlockingInfo", response_model=BlockingExplanation)
async def get_thread_blocking_info(
    thread_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> BlockingExplanation:
    """Return blocked status and human-readable blocking reasons for a thread."""
    result = await dependency_service.get_thread_blocking_info(thread_id, current_user.id, db)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )
    return result


@router.post("/threads:getBlockingInfo", response_model=BatchBlockingExplanationResponse)
async def get_threads_blocking_info(
    request: BatchBlockingExplanationRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> BatchBlockingExplanationResponse:
    """Return blocked status and human-readable blocking reasons for multiple threads."""
    threads_result = await dependency_service.get_threads_blocking_info(
        request.thread_ids, current_user.id, db
    )
    if threads_result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or more threads not found",
        )
    return BatchBlockingExplanationResponse(threads=threads_result)


@router.post(
    "/dependencies/", response_model=DependencyResponse, status_code=status.HTTP_201_CREATED
)
async def create_dependency(
    dependency_data: DependencyCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> DependencyResponse:
    """Create a hard-block dependency between owned threads or owned issues."""
    if dependency_data.source_type != dependency_data.target_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mixed thread/issue dependencies are not supported",
        )

    if dependency_data.source_id == dependency_data.target_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot create dependency on self",
        )

    if dependency_data.source_type == "thread":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Thread-level dependencies are no longer supported. "
                "Create an issue-level dependency instead: use the last issue "
                "of the source thread and the first issue of the target thread."
        ),
    )

    result, warning = await dependency_service.create_dependency(
        dependency_data.source_id, dependency_data.target_id, current_user.id, db
    )

    if not result:
        if warning == "Issue not found" or warning is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Issue not found",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=warning,
        )

    return result


@router.get("/dependencies/{dependency_id}", response_model=DependencyResponse)
async def get_dependency(
    dependency_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> DependencyResponse:
    """Fetch a single dependency owned by the current user."""
    result = await dependency_service.get_dependency(dependency_id, current_user.id, db)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dependency {dependency_id} not found",
        )
    return result


@router.patch("/dependencies/{dependency_id}", response_model=DependencyResponse)
async def update_dependency_note(
    dependency_id: int,
    data: DependencyNoteUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> DependencyResponse:
    """Update the note on a dependency owned by the current user."""
    result = await dependency_service.update_dependency_note(
        dependency_id, data.note, current_user.id, db
    )
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dependency {dependency_id} not found",
        )
    return result


@router.delete("/dependencies/{dependency_id}")
async def delete_dependency(
    dependency_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Delete a dependency and refresh denormalized blocked flags."""
    success = await dependency_service.delete_dependency(dependency_id, current_user.id, db)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dependency {dependency_id} not found",
        )
    return {"message": "Dependency deleted"}


@router.get(
    "/threads/{thread_id}/dependency-order-check",
    response_model=ThreadDependencyOrderCheckResponse,
)
async def check_thread_dependency_order(
    thread_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ThreadDependencyOrderCheckResponse:
    """Check for conflicts between dependency order and issue position order.

    Returns a list of conflicts where dependencies imply issue X should come
    before issue Y, but the current position order disagrees.
    """
    raw_conflicts = await dependency_service.check_thread_dependency_order(
        thread_id, current_user.id, db
    )
    if raw_conflicts is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )

    if not raw_conflicts:
        return ThreadDependencyOrderCheckResponse(thread_id=thread_id, conflicts=[])

    conflicts: list[DependencyOrderConflict] = []
    for conflict in raw_conflicts:
        conflict_obj = DependencyOrderConflict(
            issue_id=conflict["issue_id"],
            issue_number=conflict["issue_number"],
            position=conflict["position"],
            dependency_requires_before=[
                DependencyOrderRequirement(**req) for req in conflict["dependency_requires_before"]
            ],
            conflict=conflict["conflict"],
        )
        conflicts.append(conflict_obj)

    return ThreadDependencyOrderCheckResponse(thread_id=thread_id, conflicts=conflicts)


@router.get(
    "/threads/{thread_id}/connected",
    response_model=ThreadConnectedResponse,
)
async def get_thread_connected_threads(
    thread_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ThreadConnectedResponse:
    """Return threads connected to this one via dependencies.

    When you are reading a thread, this tells you which other threads
    are part of the same dependency web so you know there's a relationship.
    """
    result = await dependency_service.get_thread_connected_threads(thread_id, current_user.id, db)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )
    return result


#: True once :func:`mount_subrouters` has composed the dependency sub-routers into
#: :data:`router`. The router object is module-level state, so repeated
#: composition would append a second copy of every sub-route and shadow route
#: precedence with duplicates.
_subrouters_mounted = False


def mount_subrouters() -> None:
    """Compose the dependency sub-routers into :data:`router` exactly once.

    ``app/api/__init__.py`` deliberately performs no eager imports so a cold
    serverless start does not pay for the whole API surface. Composition moved
    here so the owning module owns the router it mutates.

    The sub-router modules are imported inside the function body on first call,
    so importing :mod:`app.api.dependency` alone stays cheap. Callers must
    invoke this before copying :data:`router` into an application, because
    ``FastAPI.include_router`` snapshots the included routes at call time.
    """
    global _subrouters_mounted
    if _subrouters_mounted:
        return

    from app.api import cbl_sources
    from app.api import continuity_plan
    from app.api import continuity_rule
    from app.api import continuity_template
    from app.api import custom_cbl
    from app.api import dependency_group
    from app.api import dependency_group_batch
    from app.api import issue_dependency_batch
    from app.api import reading_order_projection
    from app.api import reading_plan_release_source
    from app.api import releases
    from app.api import roll_recovery_switch

    router.include_router(issue_dependency_batch.router)
    router.include_router(dependency_group.router)
    router.include_router(dependency_group_batch.router)
    router.include_router(continuity_rule.router)
    router.include_router(continuity_plan.router)
    router.include_router(continuity_template.router)
    router.include_router(reading_order_projection.router)
    router.include_router(reading_plan_release_source.router)
    router.include_router(cbl_sources.router)
    router.include_router(custom_cbl.router)
    router.include_router(roll_recovery_switch.router, prefix="/roll")
    router.include_router(releases.router, prefix="/releases")

    _subrouters_mounted = True




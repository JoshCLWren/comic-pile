"""Dependency API endpoints (/api/v1)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import Dependency, Issue, Thread
from app.models.user import User
from app.schemas.dependency import (
    BlockingExplanation,
    DependencyCreate,
    DependencyResponse,
    ThreadDependenciesResponse,
)
from comic_pile.dependencies import (
    detect_circular_dependency,
    get_blocked_thread_ids,
    get_blocking_explanations,
    refresh_user_blocked_status,
)

router = APIRouter(tags=["dependencies"])


async def enrich_dependencies(deps: list[Dependency], db: AsyncSession) -> list[DependencyResponse]:
    """Batch-enrich dependencies with human-readable labels.

    Collects all referenced issue/thread IDs, fetches them in bulk,
    then builds DependencyResponse objects from the lookup dicts.
    """
    if not deps:
        return []

    # Collect all IDs we need to look up
    issue_ids: set[int] = set()
    thread_ids: set[int] = set()
    for dep in deps:
        if dep.source_issue_id is not None:
            issue_ids.add(dep.source_issue_id)
        if dep.target_issue_id is not None:
            issue_ids.add(dep.target_issue_id)
        if dep.source_thread_id is not None:
            thread_ids.add(dep.source_thread_id)
        if dep.target_thread_id is not None:
            thread_ids.add(dep.target_thread_id)

    # Bulk fetch issues
    issue_map: dict[int, Issue] = {}
    if issue_ids:
        result = await db.execute(select(Issue).where(Issue.id.in_(issue_ids)))
        for issue in result.scalars():
            issue_map[issue.id] = issue
            # We'll also need the parent threads for issue labels
            thread_ids.add(issue.thread_id)

    # Bulk fetch threads
    thread_map: dict[int, Thread] = {}
    if thread_ids:
        result = await db.execute(select(Thread).where(Thread.id.in_(thread_ids)))
        for thread in result.scalars():
            thread_map[thread.id] = thread

    # Build enriched responses
    responses: list[DependencyResponse] = []
    for dep in deps:
        source_label: str | None = None
        target_label: str | None = None
        source_issue_thread_id: int | None = None
        target_issue_thread_id: int | None = None

        if dep.source_issue_id is not None:
            source_issue = issue_map.get(dep.source_issue_id)
            if source_issue:
                source_issue_thread_id = source_issue.thread_id
                source_thread = thread_map.get(source_issue.thread_id)
                if source_thread:
                    source_label = f"{source_thread.title} #{source_issue.issue_number}"
        elif dep.source_thread_id is not None:
            source_thread = thread_map.get(dep.source_thread_id)
            if source_thread:
                source_label = source_thread.title

        if dep.target_issue_id is not None:
            target_issue = issue_map.get(dep.target_issue_id)
            if target_issue:
                target_issue_thread_id = target_issue.thread_id
                target_thread = thread_map.get(target_issue.thread_id)
                if target_thread:
                    target_label = f"{target_thread.title} #{target_issue.issue_number}"
        elif dep.target_thread_id is not None:
            target_thread = thread_map.get(dep.target_thread_id)
            if target_thread:
                target_label = target_thread.title

        response = DependencyResponse.model_validate(dep, from_attributes=True)
        response.source_label = source_label
        response.target_label = target_label
        response.source_issue_thread_id = source_issue_thread_id
        response.target_issue_thread_id = target_issue_thread_id
        response.is_issue_level = (
            dep.source_issue_id is not None and dep.target_issue_id is not None
        )
        responses.append(response)

    return responses


@router.get("/dependencies/blocked", response_model=list[int])
async def get_all_blocked_thread_ids(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> list[int]:
    """Return all currently blocked thread IDs for the current user."""
    blocked_ids = await get_blocked_thread_ids(current_user.id, db)
    return sorted(blocked_ids)


@router.get("/threads/{thread_id}/dependencies", response_model=ThreadDependenciesResponse)
async def list_thread_dependencies(
    thread_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ThreadDependenciesResponse:
    """List dependencies where a thread blocks others and where it is blocked."""
    thread = await db.get(Thread, thread_id)
    if not thread or thread.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )

    source_issue = Issue.__table__.alias("source_issue")
    target_issue = Issue.__table__.alias("target_issue")

    blocking_result = await db.execute(
        select(Dependency)
        .outerjoin(source_issue, Dependency.source_issue_id == source_issue.c.id)
        .where((Dependency.source_thread_id == thread_id) | (source_issue.c.thread_id == thread_id))
    )
    blocked_by_result = await db.execute(
        select(Dependency)
        .outerjoin(target_issue, Dependency.target_issue_id == target_issue.c.id)
        .where((Dependency.target_thread_id == thread_id) | (target_issue.c.thread_id == thread_id))
    )

    blocking_deps = blocking_result.scalars().all()
    blocked_by_deps = blocked_by_result.scalars().all()

    all_deps = list(blocking_deps) + list(blocked_by_deps)
    enriched = await enrich_dependencies(all_deps, db)
    blocking_count = len(blocking_deps)

    return ThreadDependenciesResponse(
        blocking=enriched[:blocking_count],
        blocked_by=enriched[blocking_count:],
    )


@router.post("/threads/{thread_id}:getBlockingInfo", response_model=BlockingExplanation)
async def get_thread_blocking_info(
    thread_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> BlockingExplanation:
    """Return blocked status and human-readable blocking reasons for a thread."""
    thread = await db.get(Thread, thread_id)
    if not thread or thread.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found",
        )

    blocked_ids = await get_blocked_thread_ids(current_user.id, db)
    if thread_id not in blocked_ids:
        return BlockingExplanation(is_blocked=False, blocking_reasons=[])

    reasons = await get_blocking_explanations(thread_id, current_user.id, db)
    return BlockingExplanation(is_blocked=True, blocking_reasons=reasons)


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
        source_thread = await db.get(Thread, dependency_data.source_id)
        target_thread = await db.get(Thread, dependency_data.target_id)

        if (
            not source_thread
            or source_thread.user_id != current_user.id
            or not target_thread
            or target_thread.user_id != current_user.id
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Thread not found",
            )

        if await detect_circular_dependency(
            dependency_data.source_id, dependency_data.target_id, "thread", db
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot create dependency: would create circular dependency",
            )

        dependency = Dependency(
            source_thread_id=dependency_data.source_id,
            target_thread_id=dependency_data.target_id,
        )
    else:
        source_issue = await db.get(Issue, dependency_data.source_id)
        target_issue = await db.get(Issue, dependency_data.target_id)
        if not source_issue or not target_issue:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Issue not found",
            )

        source_thread = await db.get(Thread, source_issue.thread_id)
        target_thread = await db.get(Thread, target_issue.thread_id)
        if (
            not source_thread
            or source_thread.user_id != current_user.id
            or not target_thread
            or target_thread.user_id != current_user.id
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Issue not found",
            )

        if await detect_circular_dependency(
            dependency_data.source_id, dependency_data.target_id, "issue", db
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot create dependency: would create circular dependency",
            )

        dependency = Dependency(
            source_issue_id=dependency_data.source_id,
            target_issue_id=dependency_data.target_id,
        )

    try:
        db.add(dependency)
        await db.flush()
    except IntegrityError as err:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dependency already exists",
        ) from err

    await refresh_user_blocked_status(current_user.id, db)
    await db.commit()
    await db.refresh(dependency)

    return (await enrich_dependencies([dependency], db))[0]


@router.get("/dependencies/{dependency_id}", response_model=DependencyResponse)
async def get_dependency(
    dependency_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> DependencyResponse:
    """Fetch a single dependency owned by the current user."""
    dependency = await db.get(Dependency, dependency_id)
    if not dependency:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dependency {dependency_id} not found",
        )
    if not await _is_dependency_owned_by_user(dependency, current_user.id, db):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dependency {dependency_id} not found",
        )
    return (await enrich_dependencies([dependency], db))[0]


@router.delete("/dependencies/{dependency_id}")
async def delete_dependency(
    dependency_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Delete a dependency and refresh denormalized blocked flags."""
    dependency = await db.get(Dependency, dependency_id)
    if not dependency:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dependency {dependency_id} not found",
        )
    if not await _is_dependency_owned_by_user(dependency, current_user.id, db):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dependency {dependency_id} not found",
        )

    await db.delete(dependency)
    await refresh_user_blocked_status(current_user.id, db)
    await db.commit()
    return {"message": "Dependency deleted"}


async def _is_dependency_owned_by_user(
    dependency: Dependency,
    user_id: int,
    db: AsyncSession,
) -> bool:
    """Return whether a dependency belongs to the given user.

    Args:
        dependency: Dependency row to validate ownership for.
        user_id: Authenticated user ID to compare against.
        db: Database session used for related Thread/Issue lookups.

    Returns:
        True when the dependency belongs to the user; otherwise False.
        For thread dependencies, ownership is checked through source_thread_id.
        For issue dependencies, ownership is checked through source_issue_id -> thread.user_id.
    """
    if dependency.source_thread_id is not None:
        source_thread = await db.get(Thread, dependency.source_thread_id)
        return bool(source_thread and source_thread.user_id == user_id)
    if dependency.source_issue_id is not None:
        source_issue = await db.get(Issue, dependency.source_issue_id)
        if not source_issue:
            return False
        source_thread = await db.get(Thread, source_issue.thread_id)
        return bool(source_thread and source_thread.user_id == user_id)
    return False

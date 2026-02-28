"""Dependency API endpoints (/api/v1)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
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
        .where(
            (Dependency.source_thread_id == thread_id) | (source_issue.c.thread_id == thread_id)
        )
    )
    blocked_by_result = await db.execute(
        select(Dependency)
        .outerjoin(target_issue, Dependency.target_issue_id == target_issue.c.id)
        .where(
            (Dependency.target_thread_id == thread_id) | (target_issue.c.thread_id == thread_id)
        )
    )

    return ThreadDependenciesResponse(
        blocking=[
            DependencyResponse.model_validate(dep, from_attributes=True)
            for dep in blocking_result.scalars().all()
        ],
        blocked_by=[
            DependencyResponse.model_validate(dep, from_attributes=True)
            for dep in blocked_by_result.scalars().all()
        ],
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


@router.post("/dependencies/", response_model=DependencyResponse, status_code=status.HTTP_201_CREATED)
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

    db.add(dependency)
    await db.flush()

    await refresh_user_blocked_status(current_user.id, db)
    await db.commit()
    await db.refresh(dependency)

    return DependencyResponse.model_validate(dependency, from_attributes=True)


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
    return DependencyResponse.model_validate(dependency, from_attributes=True)


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
    """Return True when dependency belongs to the user."""
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

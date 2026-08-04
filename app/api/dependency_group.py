"""Authenticated API for user-owned named dependency groups."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user
from app.database import get_db
from app.models import DependencyGroup, DependencyGroupMembership, Issue, Thread
from app.models.user import User
from app.schemas.dependency_group import (
    DependencyGroupCreate,
    DependencyGroupMemberCreate,
    DependencyGroupMemberResponse,
    DependencyGroupResponse,
    DependencyGroupSummary,
    DependencyGroupUpdate,
)

router = APIRouter(prefix="/reading-order-groups", tags=["reading-order-groups"])


def _normalize_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise HTTPException(status_code=422, detail="Group name must not be blank")
    return normalized


async def _owned_group(
    db: AsyncSession, group_id: int, user_id: int
) -> DependencyGroup:
    result = await db.execute(
        select(DependencyGroup)
        .options(selectinload(DependencyGroup.memberships))
        .where(DependencyGroup.id == group_id, DependencyGroup.user_id == user_id)
    )
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail=f"Group {group_id} not found")
    return group


@router.get("/", response_model=list[DependencyGroupResponse])
async def list_groups(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> list[DependencyGroup]:
    """List the current user's groups and memberships."""
    result = await db.execute(
        select(DependencyGroup)
        .options(selectinload(DependencyGroup.memberships))
        .where(DependencyGroup.user_id == current_user.id)
        .order_by(DependencyGroup.name, DependencyGroup.id)
    )
    return list(result.scalars().unique())


@router.post("/", response_model=DependencyGroupResponse, status_code=201)
async def create_group(
    payload: DependencyGroupCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> DependencyGroup:
    """Create a user-owned named group."""
    group = DependencyGroup(user_id=current_user.id, name=_normalize_name(payload.name))
    db.add(group)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="A group with this name already exists") from exc
    return await _owned_group(db, group.id, current_user.id)


@router.get("/{group_id}", response_model=DependencyGroupResponse)
async def get_group(
    group_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> DependencyGroup:
    """Return one owned group."""
    return await _owned_group(db, group_id, current_user.id)


@router.patch("/{group_id}", response_model=DependencyGroupResponse)
async def update_group(
    group_id: int,
    payload: DependencyGroupUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> DependencyGroup:
    """Rename one owned group."""
    group = await _owned_group(db, group_id, current_user.id)
    group.name = _normalize_name(payload.name)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="A group with this name already exists") from exc
    return await _owned_group(db, group_id, current_user.id)


@router.delete("/{group_id}", status_code=204)
async def delete_group(
    group_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete one owned group and its memberships."""
    group = await _owned_group(db, group_id, current_user.id)
    await db.delete(group)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{group_id}/members",
    response_model=DependencyGroupMemberResponse,
    status_code=201,
)
async def add_member(
    group_id: int,
    payload: DependencyGroupMemberCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> DependencyGroupMembership:
    """Add one owned thread or issue to an owned group."""
    await _owned_group(db, group_id, current_user.id)
    if payload.thread_id is not None:
        target = await db.get(Thread, payload.thread_id)
        if target is None or target.user_id != current_user.id:
            raise HTTPException(status_code=404, detail=f"Thread {payload.thread_id} not found")
    else:
        issue = await db.get(Issue, payload.issue_id)
        thread = await db.get(Thread, issue.thread_id) if issue else None
        if issue is None or thread is None or thread.user_id != current_user.id:
            raise HTTPException(status_code=404, detail=f"Issue {payload.issue_id} not found")
    member = DependencyGroupMembership(
        group_id=group_id,
        thread_id=payload.thread_id,
        issue_id=payload.issue_id,
    )
    db.add(member)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="This member is already in the group") from exc
    await db.refresh(member)
    return member


@router.delete("/{group_id}/members/{member_id}", status_code=204)
async def remove_member(
    group_id: int,
    member_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Remove one membership from an owned group."""
    await _owned_group(db, group_id, current_user.id)
    member = await db.get(DependencyGroupMembership, member_id)
    if member is None or member.group_id != group_id:
        raise HTTPException(status_code=404, detail=f"Member {member_id} not found")
    await db.delete(member)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/threads/{thread_id}/groups", response_model=list[DependencyGroupSummary])
async def list_thread_groups(
    thread_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> list[DependencyGroupSummary]:
    """List groups containing an owned thread or any of its owned issues."""
    thread = await db.get(Thread, thread_id)
    if thread is None or thread.user_id != current_user.id:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
    issue_ids = select(Issue.id).where(Issue.thread_id == thread_id)
    result = await db.execute(
        select(DependencyGroup.id, DependencyGroup.name)
        .join(DependencyGroupMembership)
        .where(
            DependencyGroup.user_id == current_user.id,
            or_(
                DependencyGroupMembership.thread_id == thread_id,
                DependencyGroupMembership.issue_id.in_(issue_ids),
            ),
        )
        .distinct()
        .order_by(DependencyGroup.name, DependencyGroup.id)
    )
    return [DependencyGroupSummary(id=row.id, name=row.name) for row in result]

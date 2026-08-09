"""Batched crossover membership reads for thread-oriented screens."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import DependencyGroup, DependencyGroupMembership, Issue, Thread
from app.models.user import User
from app.schemas.dependency_group import DependencyGroupSummary

router = APIRouter()
MAX_BATCH_THREADS = 200


class DependencyGroupThreadBatchRequest(BaseModel):
    """Request crossover summaries for a bounded set of owned threads."""

    thread_ids: list[int] = Field(min_length=1, max_length=MAX_BATCH_THREADS)


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
    """Return distinct crossover summaries for each requested owned thread."""
    thread_ids = list(dict.fromkeys(payload.thread_ids))
    owned_result = await db.execute(
        select(Thread.id).where(
            Thread.user_id == current_user.id,
            Thread.id.in_(thread_ids),
        )
    )
    owned_ids = set(owned_result.scalars())
    missing_ids = [thread_id for thread_id in thread_ids if thread_id not in owned_ids]
    if missing_ids:
        raise HTTPException(status_code=404, detail=f"Thread {missing_ids[0]} not found")

    result = await db.execute(
        select(
            DependencyGroupMembership.thread_id.label("direct_thread_id"),
            Issue.thread_id.label("issue_thread_id"),
            DependencyGroup.id.label("group_id"),
            DependencyGroup.name.label("group_name"),
        )
        .join(DependencyGroup, DependencyGroup.id == DependencyGroupMembership.group_id)
        .outerjoin(Issue, Issue.id == DependencyGroupMembership.issue_id)
        .where(
            DependencyGroup.user_id == current_user.id,
            or_(
                DependencyGroupMembership.thread_id.in_(thread_ids),
                Issue.thread_id.in_(thread_ids),
            ),
        )
        .order_by(DependencyGroup.name, DependencyGroup.id)
    )

    groups_by_thread: dict[int, list[DependencyGroupSummary]] = {
        thread_id: [] for thread_id in thread_ids
    }
    seen: dict[int, set[int]] = {thread_id: set() for thread_id in thread_ids}
    for row in result:
        thread_id = row.direct_thread_id if row.direct_thread_id is not None else row.issue_thread_id
        if thread_id is None or row.group_id in seen[thread_id]:
            continue
        seen[thread_id].add(row.group_id)
        groups_by_thread[thread_id].append(
            DependencyGroupSummary(id=row.group_id, name=row.group_name)
        )

    return groups_by_thread

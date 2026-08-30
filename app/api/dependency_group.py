"""Authenticated API for user-owned named dependency groups."""

from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import JSONB, insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user
from app.cache_invalidation import invalidate_user_view
from app.database import get_db
from app.models import DependencyGroup, DependencyGroupMembership, Issue, Thread
from app.models.continuity_plan import ContinuityPlan
from app.models.user import User
from app.schemas.dependency_group import (
    DependencyGroupCreate,
    DependencyGroupIssueRangeCreate,
    DependencyGroupIssueRangeResponse,
    DependencyGroupMemberCreate,
    DependencyGroupMemberResponse,
    DependencyGroupResponse,
    DependencyGroupSummary,
    DependencyGroupUpdate,
)
from comic_pile.dependencies import refresh_user_blocked_status

router = APIRouter(prefix="/reading-order-groups", tags=["reading-order-groups"])
MAX_RANGE_SIZE = 250


def _normalize_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise HTTPException(status_code=422, detail="Group name must not be blank")
    return normalized


async def _member_responses(
    db: AsyncSession, memberships: Sequence[DependencyGroupMembership]
) -> list[DependencyGroupMemberResponse]:
    """Resolve display metadata for memberships in two batched queries.

    Thread titles come from one query over the referenced threads; issue numbers
    and their series titles come from one joined query over the referenced
    issues. This avoids per-member lazy loads regardless of membership count.

    Args:
        db: The asynchronous database session.
        memberships: The persisted memberships to describe.

    Returns:
        Member payloads in input order with series titles and issue numbers.
        Targets that no longer resolve keep ``None`` metadata so clients can
        render a readable fallback instead of raw database IDs.
    """
    thread_ids = {member.thread_id for member in memberships if member.thread_id is not None}
    issue_ids = {member.issue_id for member in memberships if member.issue_id is not None}

    thread_titles: dict[int, str] = {}
    if thread_ids:
        result = await db.execute(select(Thread.id, Thread.title).where(Thread.id.in_(thread_ids)))
        thread_titles = {row.id: row.title for row in result}

    issue_metadata: dict[int, tuple[str | None, str | None]] = {}
    if issue_ids:
        result = await db.execute(
            select(Issue.id, Issue.issue_number, Thread.title)
            .join(Thread, Issue.thread_id == Thread.id)
            .where(Issue.id.in_(issue_ids))
        )
        issue_metadata = {row.id: (row.issue_number, row.title) for row in result}

    responses: list[DependencyGroupMemberResponse] = []
    for member in memberships:
        if member.thread_id is not None:
            series_title = thread_titles.get(member.thread_id)
            issue_number = None
        else:
            issue_number, series_title = issue_metadata.get(member.issue_id) or (None, None)
        responses.append(
            DependencyGroupMemberResponse(
                id=member.id,
                thread_id=member.thread_id,
                issue_id=member.issue_id,
                position=member.position,
                series_title=series_title,
                issue_number=issue_number,
            )
        )
    return responses


async def _group_response(
    db: AsyncSession, group: DependencyGroup
) -> DependencyGroupResponse:
    """Serialize one group with enriched member display metadata.

    Args:
        db: The asynchronous database session.
        group: The owned group whose memberships should be described.

    Returns:
        The group payload whose members carry resolved comic metadata.
    """
    result = await db.execute(
        select(DependencyGroupMembership)
        .where(DependencyGroupMembership.group_id == group.id)
        .order_by(DependencyGroupMembership.position, DependencyGroupMembership.id)
    )
    memberships = list(result.scalars())
    return DependencyGroupResponse(
        id=group.id,
        name=group.name,
        created_at=group.created_at,
        memberships=await _member_responses(db, memberships),
    )


async def _next_group_position(db: AsyncSession, group_id: int) -> int:
    """Return the next sequential reading-order slot for a group.

    Args:
        db: The asynchronous database session.
        group_id: The owned group whose memberships are being extended.

    Returns:
        One greater than the current maximum membership position (or ``1``
        when the group has no memberships yet).
    """
    await db.execute(
        select(DependencyGroup.id).where(DependencyGroup.id == group_id).with_for_update()
    )
    result = await db.execute(
        select(func.max(DependencyGroupMembership.position)).where(
            DependencyGroupMembership.group_id == group_id
        )
    )
    current_max = result.scalar()
    return (current_max if current_max is not None else 0) + 1


async def _refresh_crossover_blocked_state(user_id: int, db: AsyncSession) -> None:
    """Persist blocked-state changes and invalidate dependent user-scoped reads."""
    await refresh_user_blocked_status(user_id, db)
    await db.commit()
    await invalidate_user_view(user_id)


async def _owned_group(db: AsyncSession, group_id: int, user_id: int) -> DependencyGroup:
    result = await db.execute(
        select(DependencyGroup)
        .options(selectinload(DependencyGroup.memberships))
        .where(DependencyGroup.id == group_id, DependencyGroup.user_id == user_id)
    )
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail=f"Group {group_id} not found")
    return group


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
    result = await db.execute(
        select(DependencyGroup)
        .options(selectinload(DependencyGroup.memberships))
        .where(DependencyGroup.user_id == current_user.id)
        .order_by(DependencyGroup.name, DependencyGroup.id)
    )
    groups = list(result.scalars().unique())
    return [await _group_response(db, group) for group in groups]


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
    group = DependencyGroup(user_id=current_user.id, name=_normalize_name(payload.name))
    db.add(group)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="A group with this name already exists") from exc
    return await _group_response(db, await _owned_group(db, group.id, current_user.id))


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
    return await _group_response(db, await _owned_group(db, group_id, current_user.id))


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
    group = await _owned_group(db, group_id, current_user.id)
    group.name = _normalize_name(payload.name)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="A group with this name already exists") from exc
    return await _group_response(db, await _owned_group(db, group_id, current_user.id))


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
    group = await _owned_group(db, group_id, current_user.id)
    await db.delete(group)
    await db.commit()
    await _refresh_crossover_blocked_state(current_user.id, db)
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
    await _owned_group(db, group_id, current_user.id)
    thread = await db.get(Thread, payload.thread_id)
    if thread is None or thread.user_id != current_user.id:
        raise HTTPException(status_code=404, detail=f"Thread {payload.thread_id} not found")

    range_size = payload.end_position - payload.start_position + 1
    if range_size > MAX_RANGE_SIZE:
        raise HTTPException(
            status_code=422,
            detail=f"Issue range cannot contain more than {MAX_RANGE_SIZE} positions",
        )

    issue_result = await db.execute(
        select(Issue)
        .where(
            Issue.thread_id == payload.thread_id,
            Issue.position >= payload.start_position,
            Issue.position <= payload.end_position,
        )
        .order_by(Issue.position)
    )
    issues = list(issue_result.scalars())
    expected_positions = list(range(payload.start_position, payload.end_position + 1))
    actual_positions = [issue.position for issue in issues]
    if actual_positions != expected_positions:
        missing = sorted(set(expected_positions) - set(actual_positions))
        raise HTTPException(
            status_code=422,
            detail=f"Issue range contains missing positions: {', '.join(map(str, missing))}",
        )

    issue_ids = [issue.id for issue in issues]
    base_position = await _next_group_position(db, group_id)
    statement = (
        pg_insert(DependencyGroupMembership)
        .values(
            [
                {
                    "group_id": group_id,
                    "issue_id": issue_id,
                    "position": base_position + index,
                }
                for index, issue_id in enumerate(issue_ids)
            ]
        )
        .on_conflict_do_nothing(constraint="uq_dependency_group_issue")
        .returning(DependencyGroupMembership.issue_id)
    )
    added_ids = list((await db.execute(statement)).scalars())
    await db.commit()
    await _refresh_crossover_blocked_state(current_user.id, db)
    added_id_set = set(added_ids)

    return DependencyGroupIssueRangeResponse(
        thread_id=payload.thread_id,
        start_position=payload.start_position,
        end_position=payload.end_position,
        added_issue_ids=added_ids,
        already_present_issue_ids=[issue_id for issue_id in issue_ids if issue_id not in added_id_set],
    )


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
    position = await _next_group_position(db, group_id)
    member = DependencyGroupMembership(
        group_id=group_id,
        thread_id=payload.thread_id,
        issue_id=payload.issue_id,
        position=position,
    )
    db.add(member)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="This member is already in the group") from exc
    await db.refresh(member)
    response = (await _member_responses(db, [member]))[0]
    await _refresh_crossover_blocked_state(current_user.id, db)
    return response


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
    await _owned_group(db, group_id, current_user.id)
    crossover_node = {"node_type": "crossover", "ref_id": group_id}
    result = await db.execute(
        select(ContinuityPlan.id, ContinuityPlan.name)
        .where(
            ContinuityPlan.user_id == current_user.id,
            func.cast(ContinuityPlan.nodes_json, JSONB).contains([crossover_node]),
        )
        .order_by(ContinuityPlan.name, ContinuityPlan.id)
    )
    return [DependencyGroupSummary(id=row.id, name=row.name) for row in result]


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
    await _owned_group(db, group_id, current_user.id)
    member = await db.get(DependencyGroupMembership, member_id)
    if member is None or member.group_id != group_id:
        raise HTTPException(status_code=404, detail=f"Member {member_id} not found")
    await db.delete(member)
    await db.commit()
    await _refresh_crossover_blocked_state(current_user.id, db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

"""Generalized continuity-rule CRUD endpoints."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user
from app.cache import invalidate_cache
from app.continuity_rules import ensure_owned_continuity_rule_references
from app.database import get_db
from app.models.continuity_rule import ContinuityRule, ContinuityRuleSelectedMember
from app.models.user import User
from app.schemas.continuity_rule import ContinuityRuleCreate, ContinuityRuleResponse

router = APIRouter(tags=["continuity"])


async def _invalidate_continuity_caches(user_id: int) -> None:
    """Invalidate continuity and legacy blocked-state caches after a mutation."""
    await asyncio.gather(
        invalidate_cache(f"cache:continuity:*:User:{user_id}:*"),
        invalidate_cache(f"cache:get_blocked_thread_ids:{user_id}:"),
        invalidate_cache(f"cache:list_threads:User:{user_id}:*"),
        invalidate_cache(f"cache:get_thread_blocking_info:*:User:{user_id}:"),
        invalidate_cache(f"cache:get_threads_blocking_info:*:User:{user_id}:"),
    )


def _to_response(rule: ContinuityRule) -> ContinuityRuleResponse:
    """Convert a loaded persistence model into its API response."""
    return ContinuityRuleResponse(
        id=rule.id,
        user_id=rule.user_id,
        source_type=rule.source_type,
        source_id=rule.source_id,
        target_type=rule.target_type,
        target_id=rule.target_id,
        satisfaction_type=rule.satisfaction_type,
        checkpoint_issue_id=rule.checkpoint_issue_id,
        selected_member_issue_ids=sorted(member.issue_id for member in rule.selected_members),
        note=rule.note,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


async def _get_owned_rule(db: AsyncSession, user_id: int, rule_id: int) -> ContinuityRule:
    """Load one owned continuity rule with selected members."""
    result = await db.execute(
        select(ContinuityRule)
        .options(selectinload(ContinuityRule.selected_members))
        .where(ContinuityRule.id == rule_id, ContinuityRule.user_id == user_id)
    )
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Continuity rule {rule_id} not found")
    return rule


async def _would_create_cycle(
    db: AsyncSession,
    *,
    user_id: int,
    source_type: str,
    source_id: int,
    target_type: str,
    target_id: int,
    exclude_rule_id: int | None = None,
) -> bool:
    """Return whether adding source→target would close a path back to source."""
    result = await db.execute(
        select(
            ContinuityRule.id,
            ContinuityRule.source_type,
            ContinuityRule.source_id,
            ContinuityRule.target_type,
            ContinuityRule.target_id,
        ).where(ContinuityRule.user_id == user_id)
    )
    adjacency: dict[tuple[str, int], set[tuple[str, int]]] = {}
    for rule_id, existing_source_type, existing_source_id, existing_target_type, existing_target_id in result:
        if exclude_rule_id is not None and rule_id == exclude_rule_id:
            continue
        adjacency.setdefault((existing_source_type, existing_source_id), set()).add(
            (existing_target_type, existing_target_id)
        )

    source = (source_type, source_id)
    stack = [(target_type, target_id)]
    visited: set[tuple[str, int]] = set()
    while stack:
        node = stack.pop()
        if node == source:
            return True
        if node in visited:
            continue
        visited.add(node)
        stack.extend(adjacency.get(node, ()))
    return False


def _cycle_conflict(payload: ContinuityRuleCreate) -> HTTPException:
    """Build a structured cycle conflict response."""
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "continuity_cycle",
            "source": {"type": payload.source_type, "id": payload.source_id},
            "target": {"type": payload.target_type, "id": payload.target_id},
        },
    )


@router.get("/continuity-rules/", response_model=list[ContinuityRuleResponse])
async def list_continuity_rules(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> list[ContinuityRuleResponse]:
    """List the authenticated user's continuity rules."""
    result = await db.execute(
        select(ContinuityRule)
        .options(selectinload(ContinuityRule.selected_members))
        .where(ContinuityRule.user_id == current_user.id)
        .order_by(ContinuityRule.id)
    )
    return [_to_response(rule) for rule in result.scalars().all()]


@router.get("/continuity-rules/{rule_id}", response_model=ContinuityRuleResponse)
async def get_continuity_rule(
    rule_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ContinuityRuleResponse:
    """Return one owned continuity rule."""
    return _to_response(await _get_owned_rule(db, current_user.id, rule_id))


@router.post(
    "/continuity-rules/",
    response_model=ContinuityRuleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_continuity_rule(
    payload: ContinuityRuleCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ContinuityRuleResponse:
    """Create an owned continuity rule after validating references and cycles."""
    await ensure_owned_continuity_rule_references(db, user_id=current_user.id, payload=payload)
    if await _would_create_cycle(
        db,
        user_id=current_user.id,
        source_type=payload.source_type,
        source_id=payload.source_id,
        target_type=payload.target_type,
        target_id=payload.target_id,
    ):
        raise _cycle_conflict(payload)

    rule = ContinuityRule(
        user_id=current_user.id,
        source_type=payload.source_type,
        source_id=payload.source_id,
        target_type=payload.target_type,
        target_id=payload.target_id,
        satisfaction_type=payload.satisfaction_type,
        checkpoint_issue_id=payload.checkpoint_issue_id,
        note=payload.note,
        selected_members=[
            ContinuityRuleSelectedMember(issue_id=issue_id)
            for issue_id in payload.selected_member_issue_ids
        ],
    )
    db.add(rule)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "continuity_rule_exists"},
        ) from exc
    await db.refresh(rule)
    await _invalidate_continuity_caches(current_user.id)
    return _to_response(await _get_owned_rule(db, current_user.id, rule.id))


@router.put("/continuity-rules/{rule_id}", response_model=ContinuityRuleResponse)
async def update_continuity_rule(
    rule_id: int,
    payload: ContinuityRuleCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ContinuityRuleResponse:
    """Replace an owned continuity rule."""
    rule = await _get_owned_rule(db, current_user.id, rule_id)
    await ensure_owned_continuity_rule_references(db, user_id=current_user.id, payload=payload)
    if await _would_create_cycle(
        db,
        user_id=current_user.id,
        source_type=payload.source_type,
        source_id=payload.source_id,
        target_type=payload.target_type,
        target_id=payload.target_id,
        exclude_rule_id=rule_id,
    ):
        raise _cycle_conflict(payload)

    rule.source_type = payload.source_type
    rule.source_id = payload.source_id
    rule.target_type = payload.target_type
    rule.target_id = payload.target_id
    rule.satisfaction_type = payload.satisfaction_type
    rule.checkpoint_issue_id = payload.checkpoint_issue_id
    rule.note = payload.note
    rule.selected_members = [
        ContinuityRuleSelectedMember(issue_id=issue_id)
        for issue_id in payload.selected_member_issue_ids
    ]
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "continuity_rule_exists"},
        ) from exc
    await _invalidate_continuity_caches(current_user.id)
    return _to_response(await _get_owned_rule(db, current_user.id, rule_id))


@router.delete("/continuity-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_continuity_rule(
    rule_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete one owned continuity rule."""
    rule = await _get_owned_rule(db, current_user.id, rule_id)
    await db.delete(rule)
    await db.commit()
    await _invalidate_continuity_caches(current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

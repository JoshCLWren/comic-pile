"""Generalized continuity-rule CRUD endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import Select, and_, func, literal, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user
from app.cache_invalidation import invalidate_user_view
from app.continuity_rules import ensure_owned_continuity_rule_references
from app.database import get_db
from app.models.continuity_rule import ContinuityRule, ContinuityRuleSelectedMember
from app.models.user import User
from app.schemas.continuity_rule import (
    ContinuityNodeType,
    ContinuityRuleCreate,
    ContinuityRuleResponse,
    ConvergenceTarget,
)
from comic_pile.dependencies import refresh_user_blocked_status

router = APIRouter(tags=["continuity"])
CONTINUITY_LOCK_NAMESPACE = 1_129_274_964


async def _invalidate_continuity_caches(user_id: int) -> None:
    """Invalidate all user-scoped cached views after a continuity mutation."""
    await invalidate_user_view(user_id)


async def _refresh_blocked_state(user_id: int, db: AsyncSession) -> None:
    """Persist the unified Queue/Roll blocked projection after graph mutations."""
    await refresh_user_blocked_status(user_id, db)
    await db.commit()
    await _invalidate_continuity_caches(user_id)


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
        convergence_targets=[
            {"type": target["type"], "id": int(target["id"])}
            for target in (rule.convergence_targets or [])
        ],
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Continuity rule {rule_id} not found",
        )
    return rule


async def _lock_continuity_graph(db: AsyncSession, user_id: int) -> None:
    """Serialize continuity graph mutations for one user until transaction end."""
    await db.execute(
        select(func.pg_advisory_xact_lock(CONTINUITY_LOCK_NAMESPACE, user_id)),
    )


async def _would_create_cycle(
    db: AsyncSession,
    *,
    user_id: int,
    source_type: ContinuityNodeType,
    source_id: int,
    target_type: ContinuityNodeType,
    target_id: int,
    exclude_rule_id: int | None = None,
) -> bool:
    """Return whether adding source→target would close a path back to source.

    Convergence targets add implicit edges: a converged rule's target waits for
    every convergence target, so each convergence target points into the rule's
    target beyond the stored source→target edge.

    Args:
        db: Asynchronous database session.
        user_id: Authenticated user whose owned graph is being validated.
        source_type: Continuity node kind of the new edge source.
        source_id: Continuity node identifier of the new edge source.
        target_type: Continuity node kind of the new edge target.
        target_id: Continuity node identifier of the new edge target.
        exclude_rule_id: Rule identifier to skip during graph traversal.

    Returns:
        True when the new edge would close a dependency cycle.
    """
    if source_type == target_type and source_id == target_id:
        return True

    def _owned_conditions(row) -> list:
        conditions = [row.c.user_id == user_id]
        if exclude_rule_id is not None:
            conditions.append(row.c.id != exclude_rule_id)
        return conditions

    def _targets_of(rules, seed) -> Select:
        return select(
            rules.c.target_type.label("node_type"),
            rules.c.target_id.label("node_id"),
        ).join(seed, or_(
            and_(
                rules.c.source_type == seed.c.node_type,
                rules.c.source_id == seed.c.node_id,
            ),
            func.cast(rules.c.convergence_targets, JSONB).contains(
                func.jsonb_build_array(
                    func.jsonb_build_object(
                        "type",
                        seed.c.node_type,
                        "id",
                        seed.c.node_id,
                    )
                )
            ),
        ))

    edge = ContinuityRule.__table__.alias("continuity_edge")
    target_seed = (
        select(
            literal(target_type).label("node_type"),
            literal(target_id).label("node_id"),
        ).cte("target_seed_node", recursive=False)
    )
    initial_targets = _targets_of(edge, target_seed).where(*_owned_conditions(edge))

    reachable = initial_targets.cte("reachable_continuity_nodes", recursive=True)
    recursive_edge = ContinuityRule.__table__.alias("recursive_continuity_edge")
    reachable = reachable.union(
        _targets_of(recursive_edge, reachable).where(*_owned_conditions(recursive_edge))
    )

    result = await db.execute(
        select(reachable.c.node_id)
        .where(
            reachable.c.node_type == source_type,
            reachable.c.node_id == source_id,
        )
        .limit(1)
    )
    return result.first() is not None


async def _would_create_convergence_cycle(
    db: AsyncSession,
    *,
    user_id: int,
    target_type: ContinuityNodeType,
    target_id: int,
    convergence_targets: list[ConvergenceTarget],
    exclude_rule_id: int | None = None,
) -> bool:
    """Return whether a converged gate would deadlock the target node.

    A converged rule makes its target readable only once every convergence
    target is satisfied, so each convergence target acts as a dependency edge
    directed into the rule target. A self-wait (a convergence target equal to
    the rule target) or a convergence target already downstream of the rule
    target closes a dependency cycle.

    Args:
        db: Asynchronous database session.
        user_id: Authenticated user whose owned graph is being validated.
        target_type: Continuity node kind of the rule target.
        target_id: Continuity node identifier of the rule target.
        convergence_targets: The requested convergence-target edges.
        exclude_rule_id: Rule identifier to skip during graph traversal.

    Returns:
        True when a convergence target would create a cycle or self-deadlock.
    """
    for target in convergence_targets:
        if await _would_create_cycle(
            db,
            user_id=user_id,
            source_type=target.type,
            source_id=target.id,
            target_type=target_type,
            target_id=target_id,
            exclude_rule_id=exclude_rule_id,
        ):
            return True
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


@router.get(
    "/continuity-rules/",
    response_model=list[ContinuityRuleResponse],
    description="List the authenticated user's continuity rules.",
)
async def list_continuity_rules(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ContinuityRuleResponse]:
    """List the authenticated user's continuity rules.

    Args:
        current_user: Authenticated user.
        db: Asynchronous database session.

    Returns:
        Every continuity rule owned by the user, ordered by identifier.
    """
    result = await db.execute(
        select(ContinuityRule)
        .options(selectinload(ContinuityRule.selected_members))
        .where(ContinuityRule.user_id == current_user.id)
        .order_by(ContinuityRule.id)
    )
    return [_to_response(rule) for rule in result.scalars().all()]


@router.get(
    "/continuity-rules/{rule_id}",
    response_model=ContinuityRuleResponse,
    description="Return one owned continuity rule.",
)
async def get_continuity_rule(
    rule_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ContinuityRuleResponse:
    """Return one owned continuity rule.

    Args:
        rule_id: Continuity rule identifier.
        current_user: Authenticated user.
        db: Asynchronous database session.

    Returns:
        The requested owned continuity rule.
    """
    return _to_response(await _get_owned_rule(db, current_user.id, rule_id))


@router.post(
    "/continuity-rules/",
    response_model=ContinuityRuleResponse,
    status_code=status.HTTP_201_CREATED,
    description="Create an owned continuity rule after validating references and cycles.",
)
async def create_continuity_rule(
    payload: ContinuityRuleCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ContinuityRuleResponse:
    """Create an owned continuity rule after validating references and cycles.

    Args:
        payload: Validated continuity rule request.
        current_user: Authenticated user.
        db: Asynchronous database session.

    Returns:
        The newly created continuity rule.

    Raises:
        HTTPException: If references are invalid, a cycle exists, or the edge is duplicated.
    """
    await _lock_continuity_graph(db, current_user.id)
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

    if await _would_create_convergence_cycle(
        db,
        user_id=current_user.id,
        target_type=payload.target_type,
        target_id=payload.target_id,
        convergence_targets=payload.convergence_targets,
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
        convergence_targets=[
            {"type": target.type, "id": target.id}
            for target in payload.convergence_targets
        ]
        or None,
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
    await _refresh_blocked_state(current_user.id, db)
    return _to_response(await _get_owned_rule(db, current_user.id, rule.id))


@router.put(
    "/continuity-rules/{rule_id}",
    response_model=ContinuityRuleResponse,
    description="Replace an owned continuity rule.",
)
async def update_continuity_rule(
    rule_id: int,
    payload: ContinuityRuleCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ContinuityRuleResponse:
    """Replace an owned continuity rule.

    Args:
        rule_id: Continuity rule identifier.
        payload: Replacement continuity rule request.
        current_user: Authenticated user.
        db: Asynchronous database session.

    Returns:
        The updated continuity rule.

    Raises:
        HTTPException: If references are invalid, a cycle exists, or the edge is duplicated.
    """
    await _lock_continuity_graph(db, current_user.id)
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

    if await _would_create_convergence_cycle(
        db,
        user_id=current_user.id,
        target_type=payload.target_type,
        target_id=payload.target_id,
        convergence_targets=payload.convergence_targets,
        exclude_rule_id=rule_id,
    ):
        raise _cycle_conflict(payload)

    rule.source_type = payload.source_type
    rule.source_id = payload.source_id
    rule.target_type = payload.target_type
    rule.target_id = payload.target_id
    rule.satisfaction_type = payload.satisfaction_type
    rule.checkpoint_issue_id = payload.checkpoint_issue_id
    rule.convergence_targets = [
        {"type": target.type, "id": target.id}
        for target in payload.convergence_targets
    ] or None
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
    await _refresh_blocked_state(current_user.id, db)
    return _to_response(await _get_owned_rule(db, current_user.id, rule_id))


@router.delete(
    "/continuity-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    description="Delete one owned continuity rule.",
)
async def delete_continuity_rule(
    rule_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Delete one owned continuity rule.

    Args:
        rule_id: Continuity rule identifier.
        current_user: Authenticated user.
        db: Asynchronous database session.

    Returns:
        An empty 204 response.

    Raises:
        HTTPException: If the continuity rule is not owned by the user.
    """
    user_id = current_user.id
    await _lock_continuity_graph(db, user_id)
    rule = await _get_owned_rule(db, user_id, rule_id)
    await db.delete(rule)
    await db.commit()
    await _refresh_blocked_state(user_id, db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

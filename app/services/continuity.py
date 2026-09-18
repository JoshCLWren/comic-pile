"""Shared continuity helpers moved out of routers.

Public home for blocked-state refresh and response conversion helpers
used by the continuity rule, plan, and template routers.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.cache_invalidation import invalidate_user_view
from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.schemas.continuity_plan import ContinuityPlanResponse
from app.schemas.continuity_rule import ContinuityRuleResponse
from comic_pile.dependencies import refresh_user_blocked_status


async def _refresh_blocked_state(
    user_id: int, db: AsyncSession
) -> None:
    """Persist the unified Queue/Roll blocked projection after graph mutations."""
    await refresh_user_blocked_status(user_id, db)
    await db.commit()
    await invalidate_user_view(user_id)


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
        selected_member_issue_ids=sorted(
            member.issue_id for member in rule.selected_members
        ),
        note=rule.note,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def _to_plan_response(plan: ContinuityPlan) -> ContinuityPlanResponse:
    """Convert persisted JSON into the typed API contract."""
    return ContinuityPlanResponse(
        id=plan.id,
        user_id=plan.user_id,
        name=plan.name,
        ordering_mode=plan.ordering_mode,
        lanes=plan.lanes_json,
        nodes=plan.nodes_json,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )

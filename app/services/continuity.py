"""Shared continuity plan response conversion helper.

Public home for the plan response converter used by plan routers. The
continuity-rule HTTP handlers and their response conversion helpers were
retired after the same-path Rust cutover (#4848, #5162).
"""

from app.models.continuity_plan import ContinuityPlan
from app.schemas.continuity_plan import ContinuityPlanResponse


def _to_plan_response(
    plan: ContinuityPlan,
    nodes: object | None = None,
) -> ContinuityPlanResponse:
    """Convert a plan into the typed API contract.

    ``nodes`` overrides leftover ``nodes_json`` so the editor can serialize
    the membership-authoritative representation without resurrecting removed
    entries. When omitted, ``nodes_json`` is used (legacy empty-membership
    GET, including #3347 duplicate rows).
    """
    return ContinuityPlanResponse(
        id=plan.id,
        user_id=plan.user_id,
        name=plan.name,
        ordering_mode=plan.ordering_mode,
        lanes=plan.lanes_json,
        nodes=plan.nodes_json if nodes is None else nodes,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )

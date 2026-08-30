"""API route handlers."""

from app.api import analytics as analytics
from app.api import continuity_plan as continuity_plan
from app.api import continuity_readiness as continuity_readiness
from app.api import continuity_rule as continuity_rule
from app.api import continuity_template as continuity_template
from app.api import dependency as dependency
from app.api import dependency_group as dependency_group
from app.api import dependency_group_batch as dependency_group_batch
from app.api import health as health
from app.api import issue_dependency_batch as issue_dependency_batch
from app.api import reading_order_projection as reading_order_projection
from app.api import recommendation_diagnostics as recommendation_diagnostics
from app.api import releases as releases
from app.api import roll_recovery_switch as roll_recovery_switch
from app.api import taste_signal as taste_signal

dependency.router.include_router(issue_dependency_batch.router)
dependency.router.include_router(dependency_group.router)
dependency.router.include_router(dependency_group_batch.router)
dependency.router.include_router(continuity_rule.router)
dependency.router.include_router(continuity_plan.router)
dependency.router.include_router(continuity_template.router)
dependency.router.include_router(continuity_readiness.router)
dependency.router.include_router(reading_order_projection.router)
dependency.router.include_router(roll_recovery_switch.router, prefix="/roll")
dependency.router.include_router(releases.router, prefix="/releases")

__all__ = [
    "analytics",
    "continuity_plan",
    "continuity_readiness",
    "continuity_rule",
    "continuity_template",
    "dependency",
    "dependency_group",
    "dependency_group_batch",
    "health",
    "issue_dependency_batch",
    "reading_order_projection",
    "recommendation_diagnostics",
    "releases",
    "roll_recovery_switch",
    "taste_signal",
]

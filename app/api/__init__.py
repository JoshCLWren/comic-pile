"""API route handlers."""

from app.api import analytics as analytics
from app.api import continuity_readiness as continuity_readiness
from app.api import continuity_rule as continuity_rule
from app.api import dependency as dependency
from app.api import dependency_group as dependency_group
from app.api import health as health
from app.api import issue_dependency_batch as issue_dependency_batch

analytics.router.include_router(health.router)
dependency.router.include_router(issue_dependency_batch.router)
dependency.router.include_router(dependency_group.router)
dependency.router.include_router(continuity_rule.router)
dependency.router.include_router(continuity_readiness.router)

__all__ = [
    "analytics",
    "continuity_readiness",
    "continuity_rule",
    "dependency",
    "dependency_group",
    "health",
    "issue_dependency_batch",
]

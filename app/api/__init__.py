"""API route handlers."""

from app.api import analytics as analytics
from app.api import dependency as dependency
from app.api import dependency_group as dependency_group
from app.api import health as health
from app.api import issue_dependency_batch as issue_dependency_batch

analytics.router.include_router(health.router)
dependency.router.include_router(issue_dependency_batch.router)
dependency.router.include_router(dependency_group.router)

__all__ = [
    "analytics",
    "dependency",
    "dependency_group",
    "health",
    "issue_dependency_batch",
]

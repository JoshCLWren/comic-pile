"""API route handlers."""

from app.api import dependency as dependency
from app.api import dependency_group as dependency_group
from app.api import dependency_group_batch as dependency_group_batch
from app.api import issue_dependency_batch as issue_dependency_batch

dependency.router.include_router(issue_dependency_batch.router)
dependency_group.router.include_router(dependency_group_batch.router)
dependency.router.include_router(dependency_group.router)

__all__ = [
    "dependency",
    "dependency_group",
    "dependency_group_batch",
    "issue_dependency_batch",
]

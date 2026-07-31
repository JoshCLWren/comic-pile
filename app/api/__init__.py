"""API route handlers."""

from app.api import dependency as dependency
from app.api import issue_dependency_batch as issue_dependency_batch

dependency.router.include_router(issue_dependency_batch.router)

__all__ = ["dependency", "issue_dependency_batch"]

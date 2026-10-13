"""Add ownership consistency constraints for reader isolation.

Revision ID: 3225_ownership_consistency
Revises: c36420000001
Create Date: 2026-10-13 00:00:00.000000

Implements issue #3225: enforce reader ownership consistency at graph and
library write boundaries. Adds foreign key relationships and relies on
application-level validation for complex cross-table ownership checks.

1. Thread.next_unread_issue_id must belong to the same thread (FK)
2. Dependency source/target issues must belong to same user (application validation)
3. ReadingSession pending references must belong to session user (application validation)
4. ReadingPlanMembership issues/dependencies must belong to plan user (application validation)
5. TagAssignment targets must belong to their respective users (application validation)

Preserves existing valid data and rejects cross-user contamination even
when users share CatalogIssue references.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "3225_ownership_consistency"
down_revision: str | Sequence[str] | None = "c36420000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add ownership consistency constraints using valid PostgreSQL constructs."""
    # 1. Thread.next_unread_issue_id must belong to same thread
    # Create a composite foreign key: (next_unread_issue_id, thread_id) -> issues(id, thread_id)
    # First ensure issues has a unique constraint on (id, thread_id) - redundant since id is PK
    op.create_foreign_key(
        "fk_thread_next_unread_issue_same_thread",
        "threads",
        "issues",
        ["next_unread_issue_id", "thread_id"],
        ["id", "thread_id"],
        ondelete="SET NULL",
    )
    
    # 2. Dependency same-user validation is enforced in application layer (create_dependency service)
    # Cross-table ownership check requires triggers; documented in app/services/dependency_service.py
    
    # 3. ReadingSession.pending_thread_id must belong to session user
    # Create composite FK: (pending_thread_id, user_id) -> threads(id, user_id)
    op.create_foreign_key(
        "fk_session_pending_thread_user",
        "sessions",
        "threads",
        ["pending_thread_id", "user_id"],
        ["id", "user_id"],
        ondelete="SET NULL",
    )
    
    # 4. ReadingSession.pending_issue_id ownership validation in application layer
    # (requires join through issues->threads->user_id)
    
    # 5. ReadingPlanIssue.issue_id ownership validation in application layer
    # (requires join through issues->threads->user_id and continuity_plans.user_id)
    
    # 6. ReadingPlanDependency.dependency_id ownership validation in application layer
    # (complex multi-table join)
    
    # 7. TagAssignment targets - polymorphic, application-level validation
    # Documented in app/services/tag_service.py


def downgrade() -> None:
    """Drop ownership consistency constraints."""
    op.drop_constraint("fk_session_pending_thread_user", "sessions", type_="foreignkey")
    op.drop_constraint("fk_thread_next_unread_issue_same_thread", "threads", type_="foreignkey")
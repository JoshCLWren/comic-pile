"""Add ownership consistency constraints for reader isolation.

Revision ID: 3225_ownership_consistency
Revises: c34990000001
Create Date: 2026-10-13 00:00:00.000000

Implements issue #3225: enforce reader ownership consistency at graph and
library write boundaries. Adds CHECK constraints and foreign key relationships
to ensure:

1. Thread.next_unread_issue_id belongs to the same thread and user
2. Dependency source/target issues belong to the same user
3. ReadingSession pending references belong to the session user
4. ReadingPlanMembership issues/dependencies belong to the plan user
5. TagAssignment targets belong to their respective users

Preserves existing valid data and rejects cross-user contamination even
when users share CatalogIssue references.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "3225_ownership_consistency"
down_revision: str | Sequence[str] | None = "c34990000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add ownership consistency constraints."""
    
    # 1. Thread.next_unread_issue_id must belong to same thread and user
    op.create_check_constraint(
        "ck_thread_next_unread_issue_same_thread",
        "threads",
        """
        next_unread_issue_id IS NULL 
        OR (
            next_unread_issue_id IN (
                SELECT id FROM issues WHERE thread_id = threads.id
            )
        )
        """,
    )
    
    # 2. Dependency source and target issues must belong to same user
    op.create_check_constraint(
        "ck_dependency_same_user",
        "dependencies",
        """
        source_issue_id IS NOT NULL 
        AND target_issue_id IS NOT NULL
        AND EXISTS (
            SELECT 1 FROM issues i1 
            WHERE i1.id = dependencies.source_issue_id
            AND EXISTS (
                SELECT 1 FROM threads t1 
                WHERE t1.id = i1.thread_id 
                AND EXISTS (
                    SELECT 1 FROM issues i2 
                    WHERE i2.id = dependencies.target_issue_id
                    AND i2.thread_id = t1.id
                )
            )
        )
        """,
    )
    
    # 3. ReadingSession pending_thread_id must belong to session user
    op.create_check_constraint(
        "ck_session_pending_thread_user",
        "sessions",
        """
        pending_thread_id IS NULL 
        OR pending_thread_id IN (
            SELECT id FROM threads WHERE user_id = sessions.user_id
        )
        """,
    )
    
    # 4. ReadingSession pending_issue_id must belong to session user
    op.create_check_constraint(
        "ck_session_pending_issue_user",
        "sessions",
        """
        pending_issue_id IS NULL 
        OR pending_issue_id IN (
            SELECT id FROM issues i 
            JOIN threads t ON t.id = i.thread_id 
            WHERE t.user_id = sessions.user_id
        )
        """,
    )
    
    # 5. ReadingPlanIssue issue_id must belong to plan user
    op.create_check_constraint(
        "ck_reading_plan_issue_user",
        "reading_plan_issues",
        """
        issue_id IN (
            SELECT id FROM issues i 
            JOIN threads t ON t.id = i.thread_id 
            WHERE t.user_id = (
                SELECT user_id FROM continuity_plans WHERE id = reading_plan_issues.plan_id
            )
        )
        """,
    )
    
    # 6. ReadingPlanDependency dependency_id must belong to plan user
    op.create_check_constraint(
        "ck_reading_plan_dependency_user",
        "reading_plan_dependencies",
        """
        dependency_id IN (
            SELECT d.id FROM dependencies d 
            JOIN issues i_source ON i_source.id = d.source_issue_id
            JOIN issues i_target ON i_target.id = d.target_issue_id
            JOIN threads t ON t.id = i_source.thread_id
            WHERE t.user_id = (
                SELECT user_id FROM continuity_plans WHERE id = reading_plan_dependencies.plan_id
            )
            AND i_source.thread_id = i_target.thread_id  -- Ensure same thread
        )
        """,
    )
    
    # 7. TagAssignment targets must belong to their respective users
    # For Issue targets
    op.create_check_constraint(
        "ck_tag_assignment_issue_user",
        "tag_assignments",
        """
        target_type = 'Issue' 
        AND target_id IN (
            SELECT id FROM issues i 
            JOIN threads t ON t.id = i.thread_id 
            WHERE t.user_id = (
                SELECT owner_user_id FROM tags WHERE id = tag_assignments.tag_id
            )
        )
        """,
    )
    
    # For Thread targets
    op.create_check_constraint(
        "ck_tag_assignment_thread_user",
        "tag_assignments",
        """
        target_type = 'Thread' 
        AND target_id IN (
            SELECT id FROM threads WHERE user_id = (
                SELECT owner_user_id FROM tags WHERE id = tag_assignments.tag_id
            )
        )
        """,
    )
    
    # For ContinuityPlan targets (global tags only)
    op.create_check_constraint(
        "ck_tag_assignment_plan_user",
        "tag_assignments",
        """
        target_type = 'ContinuityPlan' 
        AND (
            -- Global tags can be assigned to any plan
            EXISTS (
                SELECT 1 FROM tags 
                WHERE id = tag_assignments.tag_id 
                AND scope = 'global'
            )
            OR 
            -- Private tags must belong to plan owner
            EXISTS (
                SELECT 1 FROM continuity_plans cp
                JOIN users u ON u.id = cp.user_id
                WHERE cp.id = tag_assignments.target_id
                AND u.id = (
                    SELECT owner_user_id FROM tags 
                    WHERE id = tag_assignments.tag_id 
                    AND scope = 'private'
                )
            )
        )
        """,
    )


def downgrade() -> None:
    """Drop ownership consistency constraints."""
    
    op.drop_constraint("ck_tag_assignment_plan_user", "tag_assignments", type_="check")
    op.drop_constraint("ck_tag_assignment_thread_user", "tag_assignments", type_="check")
    op.drop_constraint("ck_tag_assignment_issue_user", "tag_assignments", type_="check")
    op.drop_constraint("ck_reading_plan_dependency_user", "reading_plan_dependencies", type_="check")
    op.drop_constraint("ck_reading_plan_issue_user", "reading_plan_issues", type_="check")
    op.drop_constraint("ck_session_pending_issue_user", "sessions", type_="check")
    op.drop_constraint("ck_session_pending_thread_user", "sessions", type_="check")
    op.drop_constraint("ck_dependency_same_user", "dependencies", type_="check")
    op.drop_constraint("ck_thread_next_unread_issue_same_thread", "threads", type_="check")
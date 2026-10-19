"""Remove redundant indexes covered by unique constraints.

Revision ID: c32320000001
Revises: a613b7c9d201
Create Date: 2026-10-19 00:00:00.000000

Removes redundant indexes that are already covered by unique constraints:
- ix_issue_thread_position on issues(thread_id, position) covered by uq_issue_thread_position
- ix_user_preferences_user_id on user_preferences(user_id) covered by unique constraint on user_id
- ix_recommendation_contexts_event_id on recommendation_contexts(event_id) covered by unique constraint on event_id

These indexes add storage and write maintenance overhead without providing additional
query coverage since the unique constraints already enforce the same uniqueness guarantee.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c32320000001"
down_revision: str | Sequence[str] | None = "a613b7c9d201"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove redundant indexes covered by unique constraints.
    
    Drops the following redundant indexes:
    - ix_issue_thread_position on issues table (covered by uq_issue_thread_position)
    - ix_user_preferences_user_id on user_preferences table (covered by unique user_id constraint)
    - ix_recommendation_contexts_event_id on recommendation_contexts table (covered by unique event_id constraint)
    """
    # Remove redundant index from issues table - covered by uq_issue_thread_position constraint
    op.drop_index("ix_issue_thread_position", table_name="issues", if_exists=True)
    
    # Remove redundant index from user_preferences table - covered by unique user_id constraint
    op.drop_index("ix_user_preferences_user_id", table_name="user_preferences", if_exists=True)
    
    # Remove redundant index from recommendation_contexts table - covered by unique event_id constraint
    op.drop_index("ix_recommendation_contexts_event_id", table_name="recommendation_contexts", if_exists=True)


def downgrade() -> None:
    """Restore the redundant indexes that were removed.
    
    Recreates the indexes that were removed in the upgrade operation.
    """
    # Recreate redundant index on issues table
    op.create_index(
        "ix_issue_thread_position",
        "issues",
        ["thread_id", "position"],
        unique=False,
    )
    
    # Recreate redundant index on user_preferences table
    op.create_index(
        "ix_user_preferences_user_id",
        "user_preferences",
        ["user_id"],
        unique=False,
    )
    
    # Recreate redundant index on recommendation_contexts table
    op.create_index(
        "ix_recommendation_contexts_event_id",
        "recommendation_contexts",
        ["event_id"],
        unique=False,
    )
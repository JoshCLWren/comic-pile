"""Add unique constraint on (plan_id, issue_id) to reading_plan_issues.

Enforces the invariant that a canonical Issue may belong to a Reading Plan
at most once, regardless of lane or occurrence_id.

Revision ID: 40ba17607238
Revises: c86400000001
Create Date: 2026-10-03 18:39:26.308995
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "40ba17607238"
down_revision: Union[str, Sequence[str], None] = "c86400000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add unique constraint to enforce one membership per canonical issue per plan."""
    op.create_unique_constraint(
        "uq_reading_plan_issue_plan_issue",
        "reading_plan_issues",
        ["plan_id", "issue_id"],
    )


def downgrade() -> None:
    """Remove the unique constraint."""
    op.drop_constraint(
        "uq_reading_plan_issue_plan_issue",
        "reading_plan_issues",
        type_="unique",
    )
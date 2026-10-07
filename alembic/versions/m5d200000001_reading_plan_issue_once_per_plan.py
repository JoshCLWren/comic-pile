"""Enforce one membership per canonical issue per Reading Plan (#3037).

Revision ID: m5d200000001
Revises: k4c100000001
Create Date: 2026-10-06 00:00:00.000000

Adds ``uq_reading_plan_issue_once_per_plan`` on
``reading_plan_issues(plan_id, issue_id)`` so the database itself rejects a
second occurrence of the same canonical issue inside one plan. This is the
concurrency backstop behind the service-level gate in
``rebuild_plan_membership`` and the ``ContinuityPlanWrite`` schema check.

If this migration fails on existing duplicates, do NOT work around it here:
run ``scripts/audit_reading_plan_issue_duplicates.py`` to audit, and let
#3045 own any production reconciliation.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "m5d200000001"
down_revision: str | Sequence[str] | None = "k4c100000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the once-per-plan issue uniqueness constraint.

    Args:
        None.

    Returns:
        None.
    """
    op.create_unique_constraint(
        "uq_reading_plan_issue_once_per_plan",
        "reading_plan_issues",
        ["plan_id", "issue_id"],
    )


def downgrade() -> None:
    """Drop the once-per-plan issue uniqueness constraint.

    Args:
        None.

    Returns:
        None.
    """
    op.drop_constraint(
        "uq_reading_plan_issue_once_per_plan",
        "reading_plan_issues",
        type_="unique",
    )

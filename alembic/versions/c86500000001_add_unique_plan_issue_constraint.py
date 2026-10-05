"""Add unique constraint on plan_id and issue_id for reading_plan_issues.

Revision ID: c86500000001
Revises: c86400000001

Enforces the canonical Reading Plan membership invariant: a canonical
Issue may belong to a Reading Plan at most once. This constraint operates
at the database layer so every mutation path (API, CBL adoption, import,
concurrent requests) converges on the same guarantee.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "c86500000001"
down_revision: str | None = "c86400000001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add unique constraint on (plan_id, issue_id)."""
    op.create_unique_constraint(
        "uq_reading_plan_issue_plan_issue",
        "reading_plan_issues",
        ["plan_id", "issue_id"],
    )


def downgrade() -> None:
    """Remove unique constraint on (plan_id, issue_id)."""
    op.drop_constraint(
        "uq_reading_plan_issue_plan_issue",
        "reading_plan_issues",
        type_="unique",
    )
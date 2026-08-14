"""Add convergence targets to continuity rules.

Revision ID: c85100000001
Revises: c85000000001
Create Date: 2026-08-14 14:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c85100000001"
down_revision: str | Sequence[str] | None = "c85000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the convergence_targets JSON column and relax the checkpoint shape."""
    op.add_column(
        "continuity_rules",
        sa.Column("convergence_targets", sa.JSON(), nullable=True),
    )
    op.drop_constraint("ck_continuity_rule_satisfaction_type", "continuity_rules", type_="check")
    op.create_check_constraint(
        "ck_continuity_rule_satisfaction_type",
        "continuity_rules",
        sa.text(
            "satisfaction_type IN ("
            "'item_read', 'all_members_read', 'checkpoint', 'selected_members_read', 'converged')"
        ),
    )
    op.drop_constraint("ck_continuity_rule_checkpoint_shape", "continuity_rules", type_="check")
    op.create_check_constraint(
        "ck_continuity_rule_checkpoint_shape",
        "continuity_rules",
        sa.text(
            "(satisfaction_type = 'checkpoint' AND checkpoint_issue_id IS NOT NULL) OR "
            "(satisfaction_type = 'converged' AND convergence_targets IS NOT NULL "
            "AND convergence_targets::text <> 'null') OR "
            "(satisfaction_type NOT IN ('checkpoint', 'converged') AND checkpoint_issue_id IS NULL "
            "AND (convergence_targets IS NULL OR convergence_targets::text = 'null'))"
        ),
    )


def downgrade() -> None:
    """Remove the convergence_targets column and restore the strict checkpoint shape."""
    op.drop_constraint("ck_continuity_rule_checkpoint_shape", "continuity_rules", type_="check")
    op.create_check_constraint(
        "ck_continuity_rule_checkpoint_shape",
        "continuity_rules",
        sa.text(
            "(satisfaction_type = 'checkpoint' AND checkpoint_issue_id IS NOT NULL) OR "
            "(satisfaction_type <> 'checkpoint' AND checkpoint_issue_id IS NULL)"
        ),
    )
    op.drop_constraint("ck_continuity_rule_satisfaction_type", "continuity_rules", type_="check")
    op.create_check_constraint(
        "ck_continuity_rule_satisfaction_type",
        "continuity_rules",
        sa.text(
            "satisfaction_type IN ("
            "'item_read', 'all_members_read', 'checkpoint', 'selected_members_read')"
        ),
    )
    op.drop_column("continuity_rules", "convergence_targets")

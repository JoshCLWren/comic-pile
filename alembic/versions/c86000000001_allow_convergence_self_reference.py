"""Allow convergence rules to self-reference in ck_continuity_rule_not_self.

Convergence rules encode ``source == target`` (a node waits for its own gate
targets) which violates the original ``ck_continuity_rule_not_self`` constraint
that unconditionally forbids ``source_type = target_type AND source_id = target_id``.
This migration relaxes the constraint to permit self-references when the
``satisfaction_type`` is ``converged``.

Revision ID: c86000000001
Revises: 05f8245be921
Create Date: 2026-08-27 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c86000000001"
down_revision: str | Sequence[str] | None = "05f8245be921"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Relax not-self check to allow converged self-references."""
    op.drop_constraint("ck_continuity_rule_not_self", "continuity_rules", type_="check")
    op.create_check_constraint(
        "ck_continuity_rule_not_self",
        "continuity_rules",
        sa.text(
            "NOT (source_type = target_type AND source_id = target_id) "
            "OR satisfaction_type = 'converged'"
        ),
    )


def downgrade() -> None:
    """Restore strict not-self check (will reject any existing converged self-refs)."""
    op.drop_constraint("ck_continuity_rule_not_self", "continuity_rules", type_="check")
    op.create_check_constraint(
        "ck_continuity_rule_not_self",
        "continuity_rules",
        sa.text("NOT (source_type = target_type AND source_id = target_id)"),
    )

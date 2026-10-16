"""Add inactive Reading List mode and entry intent fields.

Revision ID: c36620000001
Revises: c36420000001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c36620000001"
down_revision: str | Sequence[str] | None = "c36420000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add defaults and constraints without changing existing list behavior."""
    op.add_column(
        "custom_cbl_lists", sa.Column("mode", sa.String(6), nullable=False, server_default="loose")
    )
    op.add_column(
        "custom_cbl_entries",
        sa.Column("gate", sa.String(14), nullable=False, server_default="none"),
    )
    op.add_column(
        "custom_cbl_entries",
        sa.Column("skipped", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_check_constraint(
        "ck_custom_cbl_lists_mode", "custom_cbl_lists", "mode IN ('strict', 'loose')"
    )
    op.create_check_constraint(
        "ck_custom_cbl_entries_gate",
        "custom_cbl_entries",
        "gate IN ('none', 'hold', 'after_previous')",
    )


def downgrade() -> None:
    """Remove inactive Reading List fields."""
    op.drop_constraint("ck_custom_cbl_entries_gate", "custom_cbl_entries", type_="check")
    op.drop_constraint("ck_custom_cbl_lists_mode", "custom_cbl_lists", type_="check")
    op.drop_column("custom_cbl_entries", "skipped")
    op.drop_column("custom_cbl_entries", "gate")
    op.drop_column("custom_cbl_lists", "mode")

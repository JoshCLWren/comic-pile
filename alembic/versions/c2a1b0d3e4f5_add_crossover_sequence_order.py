"""Add authoritative crossover sequence order to dependency group memberships.

Revision ID: c2a1b0d3e4f5
Revises: 05f8245be922
Create Date: 2026-08-30 00:00:00.000000

Adds ``sequence_order`` to ``dependency_group_memberships`` so a crossover can
carry one authoritative ordered reading sequence (issue #2047). The column is
nullable and permissive for existing rows: memberships with a null
``sequence_order`` have no declared order and do not participate in crossover
sequencing, preserving legacy behavior.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c2a1b0d3e4f5"
down_revision: str | Sequence[str] | None = "05f8245be922"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the crossover sequence order column and group/order index."""
    op.add_column(
        "dependency_group_memberships",
        sa.Column("sequence_order", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_dependency_group_memberships_group_order",
        "dependency_group_memberships",
        ["group_id", "sequence_order"],
    )


def downgrade() -> None:
    """Remove the crossover sequence order column and index."""
    op.drop_index(
        "ix_dependency_group_memberships_group_order",
        table_name="dependency_group_memberships",
    )
    op.drop_column("dependency_group_memberships", "sequence_order")

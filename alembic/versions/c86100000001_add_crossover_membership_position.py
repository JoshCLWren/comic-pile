"""Add authoritative crossover membership sequence order.

Revision ID: c86100000001
Revises: 05f8245be922
Create Date: 2026-08-30 00:00:00.000000

Crossover detail previously rendered an invented order built from each
issue's series-local ``position``. This revision gives dependency-group
memberships their own authoritative cross-series ``sequence_order`` slot.
Existing rows are backfilled in insertion order (the only preserved
historical sequence), and every future add gets an explicit sequential slot.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c86100000001"
down_revision: str | Sequence[str] | None = "05f8245be922"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add and backfill the membership sequence_order column."""
    op.add_column(
        "dependency_group_memberships",
        sa.Column("sequence_order", sa.Integer(), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE dependency_group_memberships AS dgm
            SET sequence_order = ranked.rn
            FROM (
                SELECT
                    id,
                    ROW_NUMBER() OVER (PARTITION BY group_id ORDER BY id) AS rn
                FROM dependency_group_memberships
            ) AS ranked
            WHERE dgm.id = ranked.id
            """
        )
    )
    op.alter_column(
        "dependency_group_memberships",
        "sequence_order",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.create_index(
        "ix_dependency_group_memberships_group_order",
        "dependency_group_memberships",
        ["group_id", "sequence_order"],
    )


def downgrade() -> None:
    """Drop the membership sequence_order column and its index."""
    op.drop_index(
        "ix_dependency_group_memberships_group_order",
        table_name="dependency_group_memberships",
    )
    op.drop_column("dependency_group_memberships", "sequence_order")
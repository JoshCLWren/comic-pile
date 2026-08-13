"""Add checkpoint and gate JSON columns to continuity plans.

Revision ID: c85100000001
Revises: c85000000001
Create Date: 2026-08-13 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c85100000001"
down_revision: str | Sequence[str] | None = "c85000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add durable storage for checkpoint and gate plan elements."""
    op.add_column(
        "continuity_plans",
        sa.Column(
            "checkpoints_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    op.add_column(
        "continuity_plans",
        sa.Column(
            "gates_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )


def downgrade() -> None:
    """Remove checkpoint and gate plan elements."""
    op.drop_column("continuity_plans", "gates_json")
    op.drop_column("continuity_plans", "checkpoints_json")

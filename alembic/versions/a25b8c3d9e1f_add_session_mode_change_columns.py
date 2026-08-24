"""Add session mode-change columns.

Revision ID: a25b8c3d9e1f
Revises: f616f65e0f1f
Create Date: 2026-08-24 16:00:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a25b8c3d9e1f"
down_revision: str | Sequence[str] | None = "f616f65e0f1f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("sessions", sa.Column("bandwidth", sa.Integer(), nullable=True))
    op.add_column("sessions", sa.Column("intent", sa.String(length=50), nullable=True))
    op.add_column("sessions", sa.Column("source", sa.String(length=50), nullable=True))
    op.add_column("sessions", sa.Column("confidence", sa.Float(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("sessions", "confidence")
    op.drop_column("sessions", "source")
    op.drop_column("sessions", "intent")
    op.drop_column("sessions", "bandwidth")

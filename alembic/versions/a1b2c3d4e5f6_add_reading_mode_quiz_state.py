"""Add reading-mode quiz state to sessions.

Revision ID: a1b2c3d4e5f6
Revises: cc1b32cfbcae
Create Date: 2026-08-22 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "cc1b32cfbcae"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add reading-mode columns to the sessions table."""
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("reading_bandwidth", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("reading_intent", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("reading_mode_source", sa.String(length=16), nullable=True))
        batch_op.add_column(
            sa.Column("reading_mode_suggested", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    """Remove reading-mode columns from the sessions table."""
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.drop_column("reading_mode_suggested")
        batch_op.drop_column("reading_mode_source")
        batch_op.drop_column("reading_intent")
        batch_op.drop_column("reading_bandwidth")

"""add_session_timezone

Revision ID: 1690_session_timezone
Revises: d4e5f6a7b8c9
Create Date: 2026-08-23

"""

from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "1690_session_timezone"
down_revision: str | Sequence[str] | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("timezone", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "timezone")

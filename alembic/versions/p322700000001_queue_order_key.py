"""Add nullable internal queue_order_key to threads (#3227).

Revision ID: p322700000001
Revises: p322500000001
Create Date: 2026-10-18 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "p322700000001"
down_revision: str | Sequence[str] | None = "c36690000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("threads", sa.Column("queue_order_key", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("threads", "queue_order_key")

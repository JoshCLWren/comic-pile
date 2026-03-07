"""add position field to issues

Revision ID: d5588f8456ab
Revises: c22e193a5a00
Create Date: 2026-03-06 12:13:51.163210

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d5588f8456ab"
down_revision: str | Sequence[str] | None = "c22e193a5a00"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("issues", sa.Column("position", sa.Integer(), nullable=True))
    op.execute("""
        UPDATE issues 
        SET position = subq.row_num
        FROM (
            SELECT id, row_number() OVER (PARTITION BY thread_id ORDER BY id) as row_num
            FROM issues
        ) subq
        WHERE issues.id = subq.id
    """)
    op.alter_column("issues", "position", nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("issues", "position")

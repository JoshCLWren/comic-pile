"""merge task_type and snapshots heads

Revision ID: 208af6b025aa
Revises: 2ec78b5b393a, 8268a870faef
Create Date: 2026-01-07 12:32:42.733509

"""
from collections.abc import Sequence



# revision identifiers, used by Alembic.
revision: str = '208af6b025aa'
down_revision: str | Sequence[str] | None = ('2ec78b5b393a', '8268a870faef')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

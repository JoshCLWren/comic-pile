"""merge all migration heads

Revision ID: 5c2bb704d311
Revises: cc1b32cfbcae, d1388e60c8f5
Create Date: 2026-01-04 09:17:01.344672

"""
from collections.abc import Sequence



# revision identifiers, used by Alembic.
revision: str = '5c2bb704d311'
down_revision: str | Sequence[str] | None = ('cc1b32cfbcae', 'd1388e60c8f5')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

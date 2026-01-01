"""merge_heads.

Revision ID: 5b61497bed89
Revises: 55066689bcf4, f8a3b2c1d4e5
Create Date: 2026-01-01 13:10:40.552362

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "5b61497bed89"
down_revision: str | Sequence[str] | None = ("55066689bcf4", "f8a3b2c1d4e5")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

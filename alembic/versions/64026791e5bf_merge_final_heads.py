"""merge final heads

Revision ID: 64026791e5bf
Revises: abc123def456, 9f67dfb81e8b
Create Date: 2026-03-30 07:07:18.288089

"""

from collections.abc import Sequence


# revision identifiers, used by Alembic.
revision: str = "64026791e5bf"
down_revision: str | Sequence[str] | None = ("abc123def456", "9f67dfb81e8b")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

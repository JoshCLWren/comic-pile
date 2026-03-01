"""merge issue tracking and issue dependencies heads

Revision ID: c22e193a5a00
Revises: 9f97c046466f, a4c9d8e7f6b1
Create Date: 2026-03-01 09:16:47.923174

"""

from collections.abc import Sequence


# revision identifiers, used by Alembic.
revision: str = "c22e193a5a00"
down_revision: str | Sequence[str] | None = ("9f97c046466f", "a4c9d8e7f6b1")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

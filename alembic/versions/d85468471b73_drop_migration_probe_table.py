"""Drop migration probe table.

Removes the temporary probe table created by revision 189761a06c5b.

Revision ID: d85468471b73
Revises: 189761a06c5b
Create Date: 2026-08-03 07:12:36.252517

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d85468471b73"
down_revision: str | Sequence[str] | None = "189761a06c5b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_table("_test_migration_probe")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table(
        "_test_migration_probe",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

"""Add migration probe table.

Temporary probe table to verify the Neon production migration path
in the deploy-production.yml workflow. Dropped by the next revision.

Revision ID: 189761a06c5b
Revises: d3a1c2b4e5f6
Create Date: 2026-08-03 07:12:35.524613

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "189761a06c5b"
down_revision: str | Sequence[str] | None = "d3a1c2b4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "_test_migration_probe",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("_test_migration_probe")

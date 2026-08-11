"""Add structured evidence to issue identity mappings.

Revision ID: c84600000001
Revises: c84500000001
Create Date: 2026-08-10 12:24:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "c84600000001"
down_revision: str | Sequence[str] | None = "c84500000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist structured evidence for issue identity candidates.

    Args: None
    Returns: None
    """
    op.add_column(
        "issue_external_identity_mappings",
        sa.Column("evidence_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
    )
    op.alter_column(
        "issue_external_identity_mappings",
        "evidence_json",
        server_default=None,
    )


def downgrade() -> None:
    """Remove structured issue identity candidate evidence.

    Args: None
    Returns: None
    """
    op.drop_column("issue_external_identity_mappings", "evidence_json")

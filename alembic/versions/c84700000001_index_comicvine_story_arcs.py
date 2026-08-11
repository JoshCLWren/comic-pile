"""Index ComicVine story-arc metadata lookups.

Revision ID: c84700000001
Revises: c84600000001
Create Date: 2026-08-11 04:20:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c84700000001"
down_revision: str | Sequence[str] | None = "c84600000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add a provider-metadata GIN index for containment queries.

    Returns:
        None.
    """
    op.execute(
        """
        CREATE INDEX ix_external_identity_metadata_jsonb_path
        ON external_identities
        USING gin ((metadata_json::jsonb) jsonb_path_ops)
        """
    )


def downgrade() -> None:
    """Remove the provider-metadata GIN index.

    Returns:
        None.
    """
    op.drop_index("ix_external_identity_metadata_jsonb_path", table_name="external_identities")

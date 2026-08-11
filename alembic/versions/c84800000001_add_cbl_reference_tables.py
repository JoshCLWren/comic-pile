"""Add normalized CBL reading-list reference tables.

Revision ID: c84800000001
Revises: c84700000001
Create Date: 2026-08-11 01:38:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "c84800000001"
down_revision: str | Sequence[str] | None = "c84700000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create normalized CBL source, list, and ordered-entry tables.

    Args: None
    Returns: None
    """
    op.create_table(
        "cbl_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("repository", sa.String(length=255), nullable=False),
        sa.Column("revision_sha", sa.String(length=64), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("repository"),
    )

    op.create_table(
        "cbl_source_lists",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("source_path", sa.String(length=1000), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("declared_issue_count", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("revision_sha", sa.String(length=64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["cbl_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "source_path", name="uq_cbl_source_list_path"),
    )
    op.create_index(
        "ix_cbl_source_list_source_active",
        "cbl_source_lists",
        ["source_id", "active"],
    )

    op.create_table(
        "cbl_source_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("list_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("series_name", sa.String(length=500), nullable=False),
        sa.Column("issue_number", sa.String(length=100), nullable=False),
        sa.Column("volume_year", sa.Integer(), nullable=True),
        sa.Column("publication_year", sa.Integer(), nullable=True),
        sa.Column("external_series_identity_id", sa.Integer(), nullable=True),
        sa.Column("external_issue_identity_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["list_id"], ["cbl_source_lists.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["external_series_identity_id"],
            ["external_identities.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["external_issue_identity_id"],
            ["external_identities.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("list_id", "position", name="uq_cbl_source_entry_position"),
    )
    op.create_index("ix_cbl_source_entry_list_id", "cbl_source_entries", ["list_id"])
    op.create_index(
        "ix_cbl_source_entry_series_identity",
        "cbl_source_entries",
        ["external_series_identity_id"],
    )
    op.create_index(
        "ix_cbl_source_entry_issue_identity",
        "cbl_source_entries",
        ["external_issue_identity_id"],
    )


def downgrade() -> None:
    """Remove normalized CBL reference persistence.

    Args: None
    Returns: None
    """
    op.drop_index("ix_cbl_source_entry_issue_identity", table_name="cbl_source_entries")
    op.drop_index("ix_cbl_source_entry_series_identity", table_name="cbl_source_entries")
    op.drop_index("ix_cbl_source_entry_list_id", table_name="cbl_source_entries")
    op.drop_table("cbl_source_entries")
    op.drop_index("ix_cbl_source_list_source_active", table_name="cbl_source_lists")
    op.drop_table("cbl_source_lists")
    op.drop_table("cbl_sources")

"""Add provider-independent external comic identities.

Revision ID: c84500000001
Revises: c84400000002
Create Date: 2026-08-09 22:45:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "c84500000001"
down_revision: str | Sequence[str] | None = "c84400000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _mapping_columns(owner_column: str, owner_table: str) -> list[sa.Column]:
    """Return shared mapping columns for an owned ComicPile resource."""
    return [
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(owner_column, sa.Integer(), nullable=False),
        sa.Column("external_identity_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("evidence_source", sa.String(length=100), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint([owner_column], [f"{owner_table}.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["external_identity_id"], ["external_identities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    ]


def upgrade() -> None:
    """Create external identities and non-exclusive issue/thread mappings.

    Args: None
    Returns: None
    """
    op.create_table(
        "external_identities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("entity_type", sa.String(length=20), nullable=False),
        sa.Column("external_id", sa.String(length=100), nullable=False),
        sa.Column("external_url", sa.String(length=500), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("provider_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("entity_type IN ('issue', 'series')", name="ck_external_identity_entity_type"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "entity_type", "external_id", name="uq_external_identity_provider_entity"),
    )
    op.create_index(
        "ix_external_identity_provider_type",
        "external_identities",
        ["provider", "entity_type"],
    )

    op.create_table(
        "issue_external_identity_mappings",
        *_mapping_columns("issue_id", "issues"),
        sa.Column("rejection_reason", sa.String(length=500), nullable=True),
        sa.CheckConstraint(
            "status IN ('unresolved', 'candidate', 'confirmed', 'rejected')",
            name="ck_issue_external_identity_status",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_issue_external_identity_confidence",
        ),
        sa.UniqueConstraint("issue_id", "external_identity_id", name="uq_issue_external_identity_mapping"),
    )
    op.create_index(
        "ix_issue_external_identity_issue_id",
        "issue_external_identity_mappings",
        ["issue_id"],
    )
    op.create_index(
        "ix_issue_external_identity_external_id",
        "issue_external_identity_mappings",
        ["external_identity_id"],
    )

    op.create_table(
        "thread_external_series_mappings",
        *_mapping_columns("thread_id", "threads"),
        sa.CheckConstraint(
            "status IN ('unresolved', 'candidate', 'confirmed', 'rejected')",
            name="ck_thread_external_series_status",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_thread_external_series_confidence",
        ),
        sa.UniqueConstraint(
            "thread_id",
            "external_identity_id",
            name="uq_thread_external_series_mapping",
        ),
    )
    op.create_index(
        "ix_thread_external_series_thread_id",
        "thread_external_series_mappings",
        ["thread_id"],
    )
    op.create_index(
        "ix_thread_external_series_external_id",
        "thread_external_series_mappings",
        ["external_identity_id"],
    )


def downgrade() -> None:
    """Remove provider-independent external identity persistence.

    Args: None
    Returns: None
    """
    op.drop_index("ix_thread_external_series_external_id", table_name="thread_external_series_mappings")
    op.drop_index("ix_thread_external_series_thread_id", table_name="thread_external_series_mappings")
    op.drop_table("thread_external_series_mappings")
    op.drop_index("ix_issue_external_identity_external_id", table_name="issue_external_identity_mappings")
    op.drop_index("ix_issue_external_identity_issue_id", table_name="issue_external_identity_mappings")
    op.drop_table("issue_external_identity_mappings")
    op.drop_index("ix_external_identity_provider_type", table_name="external_identities")
    op.drop_table("external_identities")

"""Add durable per-reader custom CBL source links (#4021).

Revision ID: q7c100000001
Revises: q4m500000001
Create Date: 2026-10-21 00:00:00.000000

Introduces ``custom_cbl_source_links``: one stable per-reader,
per-external-CBL-source claim pointing at an owned ``custom_cbl_lists``
row, with the source revision/hash provenance captured at first-add time.

The migration is purely additive. It never writes to existing tables, so
existing Reading Plan/Reading List progress is untouched; planned CBL
backfill or reader repair remains a separate explicit-approval gate.

This revision continues the repository's single head at
``q4m500000001``. It must never point at an interior revision: a revision
with an already-existing child forks the migration graph, leaves two
Alembic heads, and makes ``alembic upgrade head`` fail on deployment.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "q7c100000001"
down_revision: str | Sequence[str] | None = "q4m500000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create custom_cbl_source_links with unique per-reader claims.

    Args:
        None.

    Returns:
        None.
    """
    op.create_table(
        "custom_cbl_source_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("cbl_source_list_id", sa.Integer(), nullable=False),
        sa.Column("custom_cbl_list_id", sa.Integer(), nullable=False),
        sa.Column("source_revision_sha", sa.String(length=64), nullable=False),
        sa.Column("source_content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["cbl_source_list_id"], ["cbl_source_lists.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["custom_cbl_list_id"], ["custom_cbl_lists.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "cbl_source_list_id",
            name="uq_custom_cbl_source_link_user_source",
        ),
        sa.UniqueConstraint("custom_cbl_list_id", name="uq_custom_cbl_source_link_list"),
    )
    op.create_index(
        "ix_custom_cbl_source_link_source_list",
        "custom_cbl_source_links",
        ["cbl_source_list_id"],
    )


def downgrade() -> None:
    """Drop custom_cbl_source_links.

    Args:
        None.

    Returns:
        None.
    """
    op.drop_index(
        "ix_custom_cbl_source_link_source_list", table_name="custom_cbl_source_links"
    )
    op.drop_table("custom_cbl_source_links")

"""Add tags and tag_assignments tables.

Revision ID: j1a2b3c4d5e6
Revises: c86400000001
Create Date: 2026-10-03 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "j1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = "c86400000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the tags and tag_assignments tables.

    Args:
        None.

    Returns:
        None.
    """
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("normalized_name", sa.String(length=100), nullable=False),
        sa.Column("scope", sa.String(length=10), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("color", sa.String(length=7), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_tags_global_names",
        "tags",
        ["normalized_name"],
        unique=True,
        postgresql_where=sa.text("scope = 'global'"),
    )
    op.create_index(
        "uq_tags_private_names",
        "tags",
        ["owner_user_id", "normalized_name"],
        unique=True,
        postgresql_where=sa.text("scope = 'private'"),
    )
    op.create_index("ix_tags_owner_user_id", "tags", ["owner_user_id"], unique=False)
    op.create_index("ix_tags_scope", "tags", ["scope"], unique=False)
    op.create_index("ix_tags_normalized_name", "tags", ["normalized_name"], unique=False)

    op.create_table(
        "tag_assignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column("target_type", sa.String(length=50), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["tags.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tag_assignments_tag_id", "tag_assignments", ["tag_id"], unique=False)
    op.create_index(
        "ix_tag_assignments_target",
        "tag_assignments",
        ["target_type", "target_id"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_tag_assignments_target",
        "tag_assignments",
        ["tag_id", "target_type", "target_id"],
    )


def downgrade() -> None:
    """Remove the tags and tag_assignments tables.

    Args:
        None.

    Returns:
        None.
    """
    op.drop_unique_constraint("uq_tag_assignments_target", "tag_assignments")
    op.drop_index("ix_tag_assignments_target", table_name="tag_assignments")
    op.drop_index("ix_tag_assignments_tag_id", table_name="tag_assignments")
    op.drop_table("tag_assignments")
    op.drop_index("ix_tags_normalized_name", table_name="tags")
    op.drop_index("ix_tags_scope", table_name="tags")
    op.drop_index("ix_tags_owner_user_id", table_name="tags")
    op.drop_index("uq_tags_private_names", table_name="tags")
    op.drop_index("uq_tags_global_names", table_name="tags")
    op.drop_table("tags")

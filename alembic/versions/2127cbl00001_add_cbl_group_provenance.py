"""Add durable CBL provenance to dependency groups.

Revision ID: 2127cbl00001
Revises: 37a821bf4182
Create Date: 2026-09-03 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2127cbl00001"
down_revision: str | Sequence[str] | None = "37a821bf4182"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add source linkage, adopted fingerprint, and source uniqueness."""
    op.add_column(
        "dependency_groups",
        sa.Column("cbl_source_list_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "dependency_groups",
        sa.Column("cbl_source_repository", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "dependency_groups",
        sa.Column("cbl_source_path", sa.String(length=1000), nullable=True),
    )
    op.add_column(
        "dependency_groups",
        sa.Column("cbl_content_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "dependency_groups",
        sa.Column("cbl_revision_sha", sa.String(length=64), nullable=True),
    )
    op.create_foreign_key(
        "fk_dependency_groups_cbl_source_list",
        "dependency_groups",
        "cbl_source_lists",
        ["cbl_source_list_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_dependency_groups_user_cbl_source",
        "dependency_groups",
        ["user_id", "cbl_source_list_id"],
    )


def downgrade() -> None:
    """Remove CBL provenance from dependency groups."""
    op.drop_constraint(
        "uq_dependency_groups_user_cbl_source",
        "dependency_groups",
        type_="unique",
    )
    op.drop_constraint(
        "fk_dependency_groups_cbl_source_list",
        "dependency_groups",
        type_="foreignkey",
    )
    op.drop_column("dependency_groups", "cbl_revision_sha")
    op.drop_column("dependency_groups", "cbl_content_hash")
    op.drop_column("dependency_groups", "cbl_source_path")
    op.drop_column("dependency_groups", "cbl_source_repository")
    op.drop_column("dependency_groups", "cbl_source_list_id")

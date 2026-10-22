"""add custom CBL overlap decisions

Revision ID: r40180000001
Revises: q4m500000001
Create Date: 2026-10-22
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "r40180000001"
down_revision: str | Sequence[str] | None = "q4m500000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the decision version token and the owner-scoped decision table.

    Args:
        None.

    Returns:
        None.
    """
    op.add_column(
        "custom_cbl_lists",
        sa.Column(
            "overlap_decisions_updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Backs the composite owner-scoped foreign key of
    # custom_cbl_overlap_decisions: a stored decision can only name a list
    # whose owner is the same reader.
    op.create_unique_constraint(
        "uq_custom_cbl_lists_id_user",
        "custom_cbl_lists",
        ["id", "user_id"],
    )
    op.create_table(
        "custom_cbl_overlap_decisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("list_id", sa.Integer(), nullable=False),
        sa.Column("continuing_external_identity_id", sa.Integer(), nullable=False),
        sa.Column("waiting_external_identity_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["continuing_external_identity_id"],
            ["external_identities.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["waiting_external_identity_id"],
            ["external_identities.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["list_id", "user_id"],
            ["custom_cbl_lists.id", "custom_cbl_lists.user_id"],
            name="fk_custom_cbl_overlap_decision_owner_list",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "continuing_external_identity_id <> waiting_external_identity_id",
            name="ck_custom_cbl_overlap_decision_distinct_volumes",
        ),
        sa.UniqueConstraint(
            "list_id",
            "continuing_external_identity_id",
            "waiting_external_identity_id",
            name="uq_custom_cbl_overlap_decision_pair",
        ),
    )
    op.create_index(
        "ix_custom_cbl_overlap_decisions_list",
        "custom_cbl_overlap_decisions",
        ["list_id"],
        unique=False,
    )
    op.create_index(
        "ix_custom_cbl_overlap_decisions_user",
        "custom_cbl_overlap_decisions",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop the owner-scoped decision table and its list version token.

    Args:
        None.

    Returns:
        None.
    """
    op.drop_index("ix_custom_cbl_overlap_decisions_user", table_name="custom_cbl_overlap_decisions")
    op.drop_index("ix_custom_cbl_overlap_decisions_list", table_name="custom_cbl_overlap_decisions")
    op.drop_table("custom_cbl_overlap_decisions")
    op.drop_constraint("uq_custom_cbl_lists_id_user", "custom_cbl_lists", type_="unique")
    op.drop_column("custom_cbl_lists", "overlap_decisions_updated_at")

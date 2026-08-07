"""Add generalized continuity rules.

Revision ID: c84200000001
Revises: 7f41d0a9c2e1
Create Date: 2026-08-06 04:58:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "c84200000001"
down_revision: str | Sequence[str] | None = "7f41d0a9c2e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create continuity rules and selected-member persistence."""
    op.create_table(
        "continuity_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("target_type", sa.String(length=20), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("satisfaction_type", sa.String(length=32), nullable=False),
        sa.Column("checkpoint_issue_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("source_type IN ('issue', 'crossover')", name="ck_continuity_rule_source_type"),
        sa.CheckConstraint("target_type IN ('issue', 'crossover')", name="ck_continuity_rule_target_type"),
        sa.CheckConstraint("satisfaction_type IN ('item_read', 'all_members_read', 'checkpoint', 'selected_members_read')", name="ck_continuity_rule_satisfaction_type"),
        sa.CheckConstraint("NOT (source_type = target_type AND source_id = target_id)", name="ck_continuity_rule_not_self"),
        sa.CheckConstraint("(satisfaction_type = 'checkpoint' AND checkpoint_issue_id IS NOT NULL) OR (satisfaction_type <> 'checkpoint' AND checkpoint_issue_id IS NULL)", name="ck_continuity_rule_checkpoint_shape"),
        sa.ForeignKeyConstraint(["checkpoint_issue_id"], ["issues.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "source_type", "source_id", "target_type", "target_id", name="uq_continuity_rule_edge"),
    )
    op.create_index("ix_continuity_rules_user_id", "continuity_rules", ["user_id"])
    op.create_index("ix_continuity_rules_source", "continuity_rules", ["user_id", "source_type", "source_id"])
    op.create_index("ix_continuity_rules_target", "continuity_rules", ["user_id", "target_type", "target_id"])
    op.create_table(
        "continuity_rule_selected_members",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("issue_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["issue_id"], ["issues.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rule_id"], ["continuity_rules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rule_id", "issue_id", name="uq_continuity_rule_selected_member"),
    )
    op.create_index("ix_continuity_rule_selected_members_rule_id", "continuity_rule_selected_members", ["rule_id"])
    op.create_index("ix_continuity_rule_selected_members_issue_id", "continuity_rule_selected_members", ["issue_id"])


def downgrade() -> None:
    """Remove generalized continuity-rule persistence."""
    op.drop_index("ix_continuity_rule_selected_members_issue_id", table_name="continuity_rule_selected_members")
    op.drop_index("ix_continuity_rule_selected_members_rule_id", table_name="continuity_rule_selected_members")
    op.drop_table("continuity_rule_selected_members")
    op.drop_index("ix_continuity_rules_target", table_name="continuity_rules")
    op.drop_index("ix_continuity_rules_source", table_name="continuity_rules")
    op.drop_index("ix_continuity_rules_user_id", table_name="continuity_rules")
    op.drop_table("continuity_rules")

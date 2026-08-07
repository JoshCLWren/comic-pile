"""Backfill legacy issue dependencies into continuity rules.

Revision ID: c84400000001
Revises: c84200000001
Create Date: 2026-08-07 07:58:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "c84400000001"
down_revision: str | Sequence[str] | None = "c84200000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Link and backfill legacy issue dependencies as item-read continuity rules."""
    op.add_column(
        "continuity_rules",
        sa.Column("legacy_dependency_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_continuity_rules_legacy_dependency_id_dependencies",
        "continuity_rules",
        "dependencies",
        ["legacy_dependency_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_continuity_rules_legacy_dependency_id",
        "continuity_rules",
        ["legacy_dependency_id"],
    )

    # Reuse an already-equivalent generalized edge rather than creating a duplicate.
    op.execute(
        sa.text(
            """
            UPDATE continuity_rules AS rule
            SET legacy_dependency_id = dep.id
            FROM dependencies AS dep
            JOIN issues AS source_issue ON source_issue.id = dep.source_issue_id
            JOIN threads AS source_thread ON source_thread.id = source_issue.thread_id
            JOIN issues AS target_issue ON target_issue.id = dep.target_issue_id
            JOIN threads AS target_thread ON target_thread.id = target_issue.thread_id
            WHERE rule.user_id = source_thread.user_id
              AND target_thread.user_id = source_thread.user_id
              AND rule.source_type = 'issue'
              AND rule.source_id = dep.source_issue_id
              AND rule.target_type = 'issue'
              AND rule.target_id = dep.target_issue_id
              AND rule.satisfaction_type = 'item_read'
              AND rule.checkpoint_issue_id IS NULL
              AND rule.legacy_dependency_id IS NULL
            """
        )
    )

    # Insert only dependencies that were not represented by an equivalent rule.
    op.execute(
        sa.text(
            """
            INSERT INTO continuity_rules (
                user_id,
                source_type,
                source_id,
                target_type,
                target_id,
                satisfaction_type,
                checkpoint_issue_id,
                legacy_dependency_id,
                note,
                created_at,
                updated_at
            )
            SELECT
                source_thread.user_id,
                'issue',
                dep.source_issue_id,
                'issue',
                dep.target_issue_id,
                'item_read',
                NULL,
                dep.id,
                dep.note,
                dep.created_at,
                dep.created_at
            FROM dependencies AS dep
            JOIN issues AS source_issue ON source_issue.id = dep.source_issue_id
            JOIN threads AS source_thread ON source_thread.id = source_issue.thread_id
            JOIN issues AS target_issue ON target_issue.id = dep.target_issue_id
            JOIN threads AS target_thread ON target_thread.id = target_issue.thread_id
            LEFT JOIN continuity_rules AS existing
              ON existing.legacy_dependency_id = dep.id
            WHERE target_thread.user_id = source_thread.user_id
              AND existing.id IS NULL
            ON CONFLICT (user_id, source_type, source_id, target_type, target_id) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    """Remove only continuity rows linked to legacy dependencies, preserving the old table."""
    op.execute(sa.text("DELETE FROM continuity_rules WHERE legacy_dependency_id IS NOT NULL"))
    op.drop_constraint(
        "uq_continuity_rules_legacy_dependency_id",
        "continuity_rules",
        type_="unique",
    )
    op.drop_constraint(
        "fk_continuity_rules_legacy_dependency_id_dependencies",
        "continuity_rules",
        type_="foreignkey",
    )
    op.drop_column("continuity_rules", "legacy_dependency_id")

"""Add Reading Plan normalized persistence tables.

Revision ID: c86200000001
Revises: b1c2d3e4f5a6
Create Date: 2026-09-20 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c86200000001"
down_revision: str | Sequence[str] | None = "b1c2d3e4f5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add normalized Reading Plan tables and columns."""
    # Add new columns to continuity_plans
    op.add_column(
        "continuity_plans",
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.add_column(
        "continuity_plans",
        sa.Column("presentation_json", sa.JSON(), nullable=True),
    )

    # Reading Plan Lanes
    op.create_table(
        "reading_plan_lanes",
        sa.Column(
            "plan_id",
            sa.Integer(),
            sa.ForeignKey("continuity_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("lane_id", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("migration_evidence_json", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("plan_id", "lane_id", name="pk_reading_plan_lanes"),
        sa.UniqueConstraint("plan_id", "display_order", name="uq_reading_plan_lane_display_order"),
    )
    op.create_index("ix_reading_plan_lanes_plan_id", "reading_plan_lanes", ["plan_id"])

    # Reading Plan Issues
    op.create_table(
        "reading_plan_issues",
        sa.Column(
            "plan_id",
            sa.Integer(),
            sa.ForeignKey("continuity_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("occurrence_id", sa.String(length=80), nullable=False),
        sa.Column(
            "issue_id",
            sa.Integer(),
            sa.ForeignKey("issues.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("lane_id", sa.String(length=80), nullable=False),
        sa.Column("display_position", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("reader_role", sa.String(length=32), nullable=True),
        sa.Column("reader_optional", sa.Boolean(), nullable=True),
        sa.Column("is_checkpoint", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source_metadata_json", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("plan_id", "occurrence_id", name="pk_reading_plan_issues"),
        sa.ForeignKeyConstraint(
            ["plan_id", "lane_id"],
            ["reading_plan_lanes.plan_id", "reading_plan_lanes.lane_id"],
            name="fk_reading_plan_issue_lane",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "plan_id", "lane_id", "display_position", name="uq_reading_plan_issue_lane_position"
        ),
    )
    op.create_index("ix_reading_plan_issues_plan_id", "reading_plan_issues", ["plan_id"])
    op.create_index("ix_reading_plan_issues_issue_id", "reading_plan_issues", ["issue_id"])
    op.create_index("ix_reading_plan_issues_plan_issue", "reading_plan_issues", ["plan_id", "issue_id"])

    # Reading Plan Dependencies
    op.create_table(
        "reading_plan_dependencies",
        sa.Column(
            "plan_id",
            sa.Integer(),
            sa.ForeignKey("continuity_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "dependency_id",
            sa.Integer(),
            sa.ForeignKey("dependencies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("explanation", sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint("plan_id", "dependency_id", name="pk_reading_plan_dependencies"),
    )
    op.create_index("ix_reading_plan_dependencies_plan_id", "reading_plan_dependencies", ["plan_id"])
    op.create_index("ix_reading_plan_dependencies_dependency_id", "reading_plan_dependencies", ["dependency_id"])

    # Reading Plan Sources
    op.create_table(
        "reading_plan_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "plan_id",
            sa.Integer(),
            sa.ForeignKey("continuity_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("raw_source_path", sa.String(length=1000), nullable=False),
        sa.Column("repository", sa.String(length=255), nullable=True),
        sa.Column("source_path", sa.String(length=1000), nullable=True),
        sa.Column("revision_sha", sa.String(length=64), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "cbl_source_list_id",
            sa.Integer(),
            sa.ForeignKey("cbl_source_lists.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "custom_cbl_list_id",
            sa.Integer(),
            sa.ForeignKey("custom_cbl_lists.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("adopted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.UniqueConstraint(
            "plan_id",
            "raw_source_path",
            "repository",
            "source_path",
            "revision_sha",
            "content_hash",
            name="uq_reading_plan_source_snapshot",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index("ix_reading_plan_sources_plan_id", "reading_plan_sources", ["plan_id"])
    op.create_index("ix_reading_plan_sources_cbl_list", "reading_plan_sources", ["cbl_source_list_id"])
    op.create_index("ix_reading_plan_sources_custom_list", "reading_plan_sources", ["custom_cbl_list_id"])

    # Reading Plan Source Placements
    op.create_table(
        "reading_plan_source_placements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "plan_id",
            sa.Integer(),
            sa.ForeignKey("continuity_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("occurrence_id", sa.String(length=80), nullable=False),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("reading_plan_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_position", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["plan_id", "occurrence_id"],
            ["reading_plan_issues.plan_id", "reading_plan_issues.occurrence_id"],
            name="fk_reading_plan_source_placement_occurrence",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["reading_plan_sources.id"],
            name="fk_reading_plan_source_placement_source",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "plan_id",
            "occurrence_id",
            "source_id",
            "source_position",
            name="uq_reading_plan_source_placement_unique",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index("ix_reading_plan_source_placements_plan_id", "reading_plan_source_placements", ["plan_id"])
    op.create_index("ix_reading_plan_source_placements_occurrence", "reading_plan_source_placements", ["plan_id", "occurrence_id"])
    op.create_index("ix_reading_plan_source_placements_source", "reading_plan_source_placements", ["plan_id", "source_id"])


def downgrade() -> None:
    """Remove normalized Reading Plan tables and columns."""
    op.drop_index("ix_reading_plan_source_placements_source", table_name="reading_plan_source_placements")
    op.drop_index("ix_reading_plan_source_placements_occurrence", table_name="reading_plan_source_placements")
    op.drop_index("ix_reading_plan_source_placements_plan_id", table_name="reading_plan_source_placements")
    op.drop_table("reading_plan_source_placements")

    op.drop_index("ix_reading_plan_sources_custom_list", table_name="reading_plan_sources")
    op.drop_index("ix_reading_plan_sources_cbl_list", table_name="reading_plan_sources")
    op.drop_index("ix_reading_plan_sources_plan_id", table_name="reading_plan_sources")
    op.drop_table("reading_plan_sources")

    op.drop_index("ix_reading_plan_dependencies_dependency_id", table_name="reading_plan_dependencies")
    op.drop_index("ix_reading_plan_dependencies_plan_id", table_name="reading_plan_dependencies")
    op.drop_table("reading_plan_dependencies")

    op.drop_index("ix_reading_plan_issues_plan_issue", table_name="reading_plan_issues")
    op.drop_index("ix_reading_plan_issues_issue_id", table_name="reading_plan_issues")
    op.drop_index("ix_reading_plan_issues_plan_id", table_name="reading_plan_issues")
    op.drop_table("reading_plan_issues")

    op.drop_index("ix_reading_plan_lanes_plan_id", table_name="reading_plan_lanes")
    op.drop_table("reading_plan_lanes")

    op.drop_column("continuity_plans", "presentation_json")
    op.drop_column("continuity_plans", "description")

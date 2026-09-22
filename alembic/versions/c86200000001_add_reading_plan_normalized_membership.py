"""Normalize Reading Plan persistence around canonical Issues and Dependencies.

Revision ID: c86200000001
Revises: a1b2c3d4e5f7

Creates the relational plan-family tables from
``docs/READING_GRAPH_PERSISTENCE_DESIGN.md`` section 2 (Chunk 1 of the
reading-graph implementation plan):

- ``reading_plan_issues``: explicit plan-to-Issue membership join.
- ``reading_plan_dependencies``: many-plan provenance links to canonical
  Dependency edges.
- ``reading_plan_sources`` / ``reading_plan_source_placements``: immutable
  import provenance preserved from existing plan JSON.

Backfills membership and provenance from ``continuity_plans.nodes_json``
without touching Roll runtime state. Plan deletion cascades only to
plan-local rows; shared Issues and Dependencies are never deleted by plan
lifecycle. No Dependency rows are created, modified, or deleted here, and
natural Thread adjacency is not materialized.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c86200000001"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NODE_ROWS_CTE = """
node_rows AS (
    SELECT p.id AS plan_id, node
    FROM continuity_plans AS p,
        LATERAL jsonb_array_elements(p.nodes_json::text::jsonb) AS node
    WHERE jsonb_typeof(p.nodes_json::text::jsonb) = 'array'
)
"""


def upgrade() -> None:
    """Create normalized plan tables and backfill from existing plan JSON."""
    op.create_table(
        "reading_plan_issues",
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("occurrence_id", sa.String(length=80), nullable=False),
        sa.Column("issue_id", sa.Integer(), nullable=False),
        sa.Column("lane_id", sa.String(length=80), nullable=False),
        sa.Column("display_position", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("reader_role", sa.String(length=32), nullable=True),
        sa.Column("reader_optional", sa.Boolean(), nullable=True),
        sa.Column("is_checkpoint", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("source_metadata_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["plan_id"], ["continuity_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["issue_id"], ["issues.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("plan_id", "occurrence_id"),
        sa.UniqueConstraint(
            "plan_id",
            "lane_id",
            "display_position",
            name="uq_reading_plan_issue_lane_position",
        ),
    )
    op.create_index(
        "ix_reading_plan_issues_plan_issue", "reading_plan_issues", ["plan_id", "issue_id"]
    )
    op.create_index(
        "ix_reading_plan_issues_issue_id", "reading_plan_issues", ["issue_id"]
    )

    op.create_table(
        "reading_plan_dependencies",
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("dependency_id", sa.Integer(), nullable=False),
        sa.Column("explanation", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["plan_id"], ["continuity_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dependency_id"], ["dependencies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("plan_id", "dependency_id"),
    )
    op.create_index(
        "ix_reading_plan_dependencies_dependency_id",
        "reading_plan_dependencies",
        ["dependency_id"],
    )

    op.create_table(
        "reading_plan_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("raw_source_path", sa.String(length=1000), nullable=False),
        sa.Column("repository", sa.String(length=255), nullable=True),
        sa.Column("source_path", sa.String(length=1000), nullable=True),
        sa.Column("revision_sha", sa.String(length=64), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("cbl_source_list_id", sa.Integer(), nullable=True),
        sa.Column("custom_cbl_list_id", sa.Integer(), nullable=True),
        sa.Column("adopted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["plan_id"], ["continuity_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["cbl_source_list_id"], ["cbl_source_lists.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["custom_cbl_list_id"], ["custom_cbl_lists.id"], ondelete="SET NULL"
        ),
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
    op.create_index(
        "ix_reading_plan_sources_plan_id", "reading_plan_sources", ["plan_id"]
    )

    op.create_table(
        "reading_plan_source_placements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("occurrence_id", sa.String(length=80), nullable=False),
        sa.Column("plan_source_id", sa.Integer(), nullable=False),
        sa.Column("source_position", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["plan_id"], ["continuity_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["plan_source_id"], ["reading_plan_sources.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "plan_id",
            "occurrence_id",
            "plan_source_id",
            "source_position",
            name="uq_reading_plan_source_placement",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        "ix_reading_plan_source_placements_plan_id",
        "reading_plan_source_placements",
        ["plan_id"],
    )
    op.create_index(
        "ix_reading_plan_source_placements_source_id",
        "reading_plan_source_placements",
        ["plan_source_id"],
    )

    _backfill_membership()
    _backfill_sources()
    _backfill_placements()


def _backfill_membership() -> None:
    """Populate plan-to-Issue rows from existing issue-type plan nodes."""
    op.execute(
        sa.text(
            f"""
WITH {_NODE_ROWS_CTE}
INSERT INTO reading_plan_issues (
    plan_id, occurrence_id, issue_id, lane_id, display_position,
    label, reader_role, reader_optional, is_checkpoint, source_metadata_json
)
SELECT
    n.plan_id,
    n.node ->> 'id',
    (n.node ->> 'ref_id')::integer,
    n.node ->> 'lane_id',
    (n.node ->> 'position')::integer,
    NULLIF(n.node ->> 'label', ''),
    NULLIF(n.node ->> 'reader_role', ''),
    (n.node ->> 'reader_optional')::boolean,
    COALESCE((n.node ->> 'is_checkpoint')::boolean, false),
    NULLIF(
        jsonb_strip_nulls(jsonb_build_object(
            'source_role', n.node ->> 'source_role',
            'source_confidence', n.node ->> 'source_confidence',
            'source_explanation', n.node ->> 'source_explanation',
            'source_story_arc_ids', n.node -> 'source_story_arc_ids',
            'source_target_story_arc_id', n.node ->> 'source_target_story_arc_id'
        ))::text,
        '{{}}'
    )::jsonb
FROM node_rows AS n
WHERE n.node ->> 'node_type' = 'issue'
    AND n.node ->> 'id' IS NOT NULL
    AND n.node ->> 'lane_id' IS NOT NULL
    AND n.node ->> 'ref_id' ~ '^[0-9]+$'
    AND n.node ->> 'position' ~ '^[0-9]+$'
    AND EXISTS (
        SELECT 1 FROM issues WHERE issues.id = (n.node ->> 'ref_id')::integer
    )
ON CONFLICT DO NOTHING
"""
        )
    )


def _backfill_sources() -> None:
    """Preserve distinct per-plan source paths as immutable snapshots.

    Existing plan JSON records only raw path strings (bare ``source_paths``
    entries and ``source_cbl_placements`` path/position pairs); repository,
    revision, and hash were never persisted, so those stay explicitly unknown
    rather than invented.
    """
    op.execute(
        sa.text(
            f"""
WITH {_NODE_ROWS_CTE},
distinct_paths AS (
    SELECT DISTINCT n.plan_id, elem AS raw_path
    FROM node_rows AS n,
        LATERAL jsonb_array_elements_text(
            CASE WHEN jsonb_typeof(n.node -> 'source_paths') = 'array'
                THEN n.node -> 'source_paths'
                ELSE '[]'::jsonb END
        ) AS elem
    WHERE elem IS NOT NULL AND elem <> ''
    UNION
    SELECT DISTINCT n.plan_id, placement ->> 'source_path'
    FROM node_rows AS n,
        LATERAL jsonb_array_elements(
            CASE WHEN jsonb_typeof(n.node -> 'source_cbl_placements') = 'array'
                THEN n.node -> 'source_cbl_placements'
                ELSE '[]'::jsonb END
        ) AS placement
    WHERE placement ->> 'source_path' IS NOT NULL
        AND placement ->> 'source_path' <> ''
)
INSERT INTO reading_plan_sources (plan_id, raw_source_path, recorded_at, metadata_json)
SELECT
    plan_id,
    raw_path,
    now(),
    jsonb_build_object(
        'migration_note',
        'backfilled from nodes_json; repository/revision/hash unknown'
    )
FROM distinct_paths
ON CONFLICT DO NOTHING
"""
        )
    )


def _backfill_placements() -> None:
    """Preserve original source positions alongside known source associations.

    CBL placements keep their recorded position; bare ``source_paths``
    associations keep a NULL position meaning known association without a
    recorded placement.
    """
    op.execute(
        sa.text(
            f"""
WITH {_NODE_ROWS_CTE},
positioned AS (
    SELECT
        n.plan_id,
        n.node ->> 'id' AS occurrence_id,
        placement ->> 'source_path' AS raw_path,
        CASE WHEN placement ->> 'position' ~ '^-?[0-9]+$'
            THEN (placement ->> 'position')::integer END AS source_position
    FROM node_rows AS n,
        LATERAL jsonb_array_elements(
            CASE WHEN jsonb_typeof(n.node -> 'source_cbl_placements') = 'array'
                THEN n.node -> 'source_cbl_placements'
                ELSE '[]'::jsonb END
        ) AS placement
    WHERE n.node ->> 'id' IS NOT NULL
        AND placement ->> 'source_path' IS NOT NULL
        AND placement ->> 'source_path' <> ''
),
unpositioned AS (
    SELECT DISTINCT
        n.plan_id,
        n.node ->> 'id' AS occurrence_id,
        elem AS raw_path,
        NULL::integer AS source_position
    FROM node_rows AS n,
        LATERAL jsonb_array_elements_text(
            CASE WHEN jsonb_typeof(n.node -> 'source_paths') = 'array'
                THEN n.node -> 'source_paths'
                ELSE '[]'::jsonb END
        ) AS elem
    WHERE n.node ->> 'id' IS NOT NULL
        AND elem IS NOT NULL AND elem <> ''
),
combined AS (
    SELECT * FROM positioned
    UNION
    SELECT * FROM unpositioned
)
INSERT INTO reading_plan_source_placements (
    plan_id, occurrence_id, plan_source_id, source_position
)
SELECT c.plan_id, c.occurrence_id, s.id, c.source_position
FROM combined AS c
JOIN reading_plan_sources AS s
    ON s.plan_id = c.plan_id AND s.raw_source_path = c.raw_path
ON CONFLICT DO NOTHING
"""
        )
    )


def downgrade() -> None:
    """Remove normalized plan tables (JSON compatibility columns are untouched)."""
    op.drop_index(
        "ix_reading_plan_source_placements_source_id",
        table_name="reading_plan_source_placements",
    )
    op.drop_index(
        "ix_reading_plan_source_placements_plan_id",
        table_name="reading_plan_source_placements",
    )
    op.drop_table("reading_plan_source_placements")
    op.drop_index("ix_reading_plan_sources_plan_id", table_name="reading_plan_sources")
    op.drop_table("reading_plan_sources")
    op.drop_index(
        "ix_reading_plan_dependencies_dependency_id",
        table_name="reading_plan_dependencies",
    )
    op.drop_table("reading_plan_dependencies")
    op.drop_index("ix_reading_plan_issues_issue_id", table_name="reading_plan_issues")
    op.drop_index("ix_reading_plan_issues_plan_issue", table_name="reading_plan_issues")
    op.drop_table("reading_plan_issues")

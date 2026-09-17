"""Add performance_metrics table for production startup and page-load tracking

Revision ID: b1c2d3e4f5a6
Revises: d901cba10001
Create Date: 2026-09-17 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1c2d3e4f5a6"
down_revision: str | Sequence[str] | None = "d901cba10001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create performance_metrics table."""
    op.create_table(
        "performance_metrics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deployment_id", sa.String(255), nullable=True),
        sa.Column("request_path", sa.String(500), nullable=True),
        sa.Column("metric_type", sa.String(100), nullable=False),
        sa.Column("cold", sa.Boolean(), nullable=False),
        sa.Column("response_time_ms", sa.Float(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )
    op.create_index("ix_perf_metrics_deployment_id", "performance_metrics", ["deployment_id"])
    op.create_index("ix_perf_metrics_metric_type", "performance_metrics", ["metric_type"])
    op.create_index("ix_perf_metrics_cold", "performance_metrics", ["cold"])
    op.create_index(
        "ix_perf_metric_type_cold",
        "performance_metrics",
        ["metric_type", "cold"],
    )
    op.create_index(
        "ix_perf_metric_timestamp",
        "performance_metrics",
        ["timestamp"],
    )


def downgrade() -> None:
    """Drop performance_metrics table."""
    op.drop_table("performance_metrics")

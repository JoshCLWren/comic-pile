"""Add session bandwidth update timestamp and validation constraints.

Revision ID: c85900000001
Revises: c85800000001
Create Date: 2026-08-25 00:00:00.000000

Completes the ephemeral session bandwidth schema (issues #1706/#1708): the
bandwidth columns themselves landed in c85600000001; this revision adds the
``bandwidth_updated_at`` lifecycle timestamp plus CHECK constraints that keep
persisted enum values and confidence inside their valid ranges. Every change
is nullable/permissive for existing rows.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c85900000001"
down_revision: str | Sequence[str] | None = "c85800000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BANDWIDTH_VALUES = ("light", "balanced", "deep")
_BANDWIDTH_SOURCE_VALUES = ("inferred", "manual", "snooze", "quiz")


def upgrade() -> None:
    """Add the bandwidth update timestamp and enum/range constraints."""
    op.add_column(
        "sessions",
        sa.Column("bandwidth_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_sessions_predicted_bandwidth_valid",
        "sessions",
        f"predicted_bandwidth IS NULL OR predicted_bandwidth IN {_format_in_list(_BANDWIDTH_VALUES)}",
    )
    op.create_check_constraint(
        "ck_sessions_active_bandwidth_valid",
        "sessions",
        f"active_bandwidth IS NULL OR active_bandwidth IN {_format_in_list(_BANDWIDTH_VALUES)}",
    )
    op.create_check_constraint(
        "ck_sessions_bandwidth_source_valid",
        "sessions",
        f"bandwidth_source IS NULL OR bandwidth_source IN {_format_in_list(_BANDWIDTH_SOURCE_VALUES)}",
    )
    op.create_check_constraint(
        "ck_sessions_bandwidth_confidence_range",
        "sessions",
        "bandwidth_confidence IS NULL "
        "OR (bandwidth_confidence >= 0 AND bandwidth_confidence <= 1)",
    )


def downgrade() -> None:
    """Drop the bandwidth constraints and update timestamp."""
    op.drop_constraint("ck_sessions_bandwidth_confidence_range", "sessions", type_="check")
    op.drop_constraint("ck_sessions_bandwidth_source_valid", "sessions", type_="check")
    op.drop_constraint("ck_sessions_active_bandwidth_valid", "sessions", type_="check")
    op.drop_constraint("ck_sessions_predicted_bandwidth_valid", "sessions", type_="check")
    op.drop_column("sessions", "bandwidth_updated_at")


def _format_in_list(values: tuple[str, ...]) -> str:
    """Render a Python string tuple as a SQL IN-list literal.

    Args:
        values: Allowed string values.

    Returns:
        SQL fragment such as ``('light', 'balanced', 'deep')``.
    """
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"

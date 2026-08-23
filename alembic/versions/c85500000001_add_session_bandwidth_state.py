"""Add ephemeral bandwidth state to reading sessions.

Revision ID: c85500000001
Revises: c85400000001
Create Date: 2026-08-23 00:00:00.000000

Adds nullable, session-scoped bandwidth state (issue #1706): predicted and
active bandwidth, confidence, provenance source, mode version, and update
timestamp. Existing rows stay valid because every column is nullable; CHECK
constraints reject invalid enum values and out-of-range confidence.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c85500000001"
down_revision: str | Sequence[str] | None = "c85400000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BANDWIDTH_VALUES = ("light", "balanced", "deep")
_BANDWIDTH_SOURCE_VALUES = ("inferred", "manual", "snooze", "quiz")


def upgrade() -> None:
    """Add nullable ephemeral bandwidth columns with validation constraints."""
    op.add_column("sessions", sa.Column("predicted_bandwidth", sa.String(20), nullable=True))
    op.add_column("sessions", sa.Column("active_bandwidth", sa.String(20), nullable=True))
    op.add_column("sessions", sa.Column("bandwidth_confidence", sa.Float(), nullable=True))
    op.add_column("sessions", sa.Column("bandwidth_source", sa.String(20), nullable=True))
    op.add_column("sessions", sa.Column("bandwidth_mode_version", sa.Integer(), nullable=True))
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
    """Drop the ephemeral bandwidth columns and their constraints."""
    op.drop_constraint("ck_sessions_bandwidth_confidence_range", "sessions", type_="check")
    op.drop_constraint("ck_sessions_bandwidth_source_valid", "sessions", type_="check")
    op.drop_constraint("ck_sessions_active_bandwidth_valid", "sessions", type_="check")
    op.drop_constraint("ck_sessions_predicted_bandwidth_valid", "sessions", type_="check")
    op.drop_column("sessions", "bandwidth_updated_at")
    op.drop_column("sessions", "bandwidth_mode_version")
    op.drop_column("sessions", "bandwidth_source")
    op.drop_column("sessions", "bandwidth_confidence")
    op.drop_column("sessions", "active_bandwidth")
    op.drop_column("sessions", "predicted_bandwidth")


def _format_in_list(values: tuple[str, ...]) -> str:
    """Render a Python string tuple as a SQL IN-list literal.

    Args:
        values: Allowed string values.

    Returns:
        SQL fragment such as ``('light', 'balanced', 'deep')``.
    """
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"

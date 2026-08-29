"""Add CHECK constraints for ephemeral session reading-intent state.

Revision ID: 05f8245be922
Revises: c85900000002
Create Date: 2026-08-29 00:00:00.000000

Completes the ephemeral session reading-intent schema (issue #1728): the
intent columns themselves landed in ``h9i0j1k2l3m4``; this revision adds CHECK
constraints, symmetric to the bandwidth constraints created in
``c85900000001``, so persisted intent enum values and confidence stay inside
their valid ranges. Every change is nullable/permissive for existing rows so
legacy sessions remain valid.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "05f8245be922"
down_revision: str | Sequence[str] | None = "c85900000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INTENT_VALUES = ("balanced", "momentum", "familiar", "explore", "random")
_INTENT_SOURCE_VALUES = ("inferred", "manual", "snooze", "quiz")


def upgrade() -> None:
    """Add enum/range CHECK constraints for the session intent columns."""
    op.create_check_constraint(
        "ck_sessions_active_intent_valid",
        "sessions",
        f"active_intent IS NULL OR active_intent IN {_format_in_list(_INTENT_VALUES)}",
    )
    op.create_check_constraint(
        "ck_sessions_predicted_intent_valid",
        "sessions",
        f"predicted_intent IS NULL OR predicted_intent IN {_format_in_list(_INTENT_VALUES)}",
    )
    op.create_check_constraint(
        "ck_sessions_intent_source_valid",
        "sessions",
        f"intent_source IS NULL OR intent_source IN {_format_in_list(_INTENT_SOURCE_VALUES)}",
    )
    op.create_check_constraint(
        "ck_sessions_intent_confidence_range",
        "sessions",
        "intent_confidence IS NULL "
        "OR (intent_confidence >= 0 AND intent_confidence <= 1)",
    )


def downgrade() -> None:
    """Drop the session intent CHECK constraints."""
    op.drop_constraint("ck_sessions_intent_confidence_range", "sessions", type_="check")
    op.drop_constraint("ck_sessions_intent_source_valid", "sessions", type_="check")
    op.drop_constraint("ck_sessions_predicted_intent_valid", "sessions", type_="check")
    op.drop_constraint("ck_sessions_active_intent_valid", "sessions", type_="check")


def _format_in_list(values: tuple[str, ...]) -> str:
    """Render a Python string tuple as a SQL IN-list literal.

    Args:
        values: Allowed string values.

    Returns:
        SQL fragment such as ``('balanced', 'random')``.
    """
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"

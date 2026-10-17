"""Add explicit prerequisite provenance without classifying historical edges.

Revision ID: c36690000001
Revises: p322500000001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c36690000001"
down_revision: str | Sequence[str] | None = "p322500000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable metadata; preserve all existing endpoints, notes and history."""
    op.add_column("dependencies", sa.Column("origin", sa.String(20), nullable=True))
    op.add_column("dependencies", sa.Column("classification", sa.String(1), nullable=True))
    op.add_column("dependencies", sa.Column("provenance", sa.String(2000), nullable=True))
    op.create_check_constraint(
        "ck_dependency_origin",
        "dependencies",
        "origin IS NULL OR origin IN ('reader', 'converted')",
    )
    op.create_check_constraint(
        "ck_dependency_classification",
        "dependencies",
        "classification IS NULL OR classification IN ('A', 'B', 'C', 'D')",
    )
    op.create_check_constraint(
        "ck_dependency_converted_provenance",
        "dependencies",
        "origin IS DISTINCT FROM 'converted' OR "
        "(classification IS NOT NULL AND provenance IS NOT NULL)",
    )


def downgrade() -> None:
    """Remove only additive metadata; retain the prerequisite rows."""
    for name in (
        "ck_dependency_converted_provenance",
        "ck_dependency_classification",
        "ck_dependency_origin",
    ):
        op.drop_constraint(name, "dependencies", type_="check")
    for name in ("provenance", "classification", "origin"):
        op.drop_column("dependencies", name)

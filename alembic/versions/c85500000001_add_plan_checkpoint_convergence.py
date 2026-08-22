"""Add checkpoint and convergence-gate semantics to continuity plans.

Revision ID: c85500000001
Revises: c85400000001
Create Date: 2026-08-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c85500000001"
down_revision: str | Sequence[str] | None = "c85400000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add checkpoint and convergence-gate JSON payloads to continuity plans."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = {column["name"] for column in inspector.get_columns("continuity_plans")}

    with op.batch_alter_table("continuity_plans") as batch_op:
        if "checkpoints_json" not in existing_columns:
            batch_op.add_column(
                sa.Column("checkpoints_json", sa.JSON(), nullable=False, server_default="[]")
            )
        if "convergence_gates_json" not in existing_columns:
            batch_op.add_column(
                sa.Column(
                    "convergence_gates_json", sa.JSON(), nullable=False, server_default="[]"
                )
            )


def downgrade() -> None:
    """Remove checkpoint and convergence-gate JSON payloads from continuity plans."""
    with op.batch_alter_table("continuity_plans") as batch_op:
        batch_op.drop_column("convergence_gates_json")
        batch_op.drop_column("checkpoints_json")

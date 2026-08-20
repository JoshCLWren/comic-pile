"""Repair schema objects affected by the historical duplicate c852 revision.

Revision ID: c85300000001
Revises: c85200000001
Create Date: 2026-08-20 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c85300000001"
down_revision: str | Sequence[str] | None = "c85200000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _index_names(table_name: str) -> set[str]:
    """Return existing index names for one table."""
    inspector = sa.inspect(op.get_bind())
    return {str(index["name"]) for index in inspector.get_indexes(table_name) if index.get("name")}


def upgrade() -> None:
    """Ensure both schema changes from the old duplicate c852 revision exist."""
    inspector = sa.inspect(op.get_bind())
    table_names = set(inspector.get_table_names())

    if "user_preferences" not in table_names:
        op.create_table(
            "user_preferences",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey(
                    "users.id",
                    name="fk_user_preferences_user_id_users",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "theme",
                sa.String(50),
                nullable=False,
                server_default="classic",
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", name="uq_user_preferences_user_id"),
        )
        op.create_index("ix_user_preferences_user_id", "user_preferences", ["user_id"])
    elif "ix_user_preferences_user_id" not in _index_names("user_preferences"):
        op.create_index("ix_user_preferences_user_id", "user_preferences", ["user_id"])

    if "ix_event_type_issue_id" not in _index_names("events"):
        op.create_index(
            "ix_event_type_issue_id",
            "events",
            ["type", "issue_id"],
            unique=False,
        )


def downgrade() -> None:
    """Preserve objects that are now canonical members of revision c852."""

"""Remove collections persistence.

Revision ID: d3a1c2b4e5f6
Revises: 4d2403b3a9ac
Create Date: 2026-08-03 10:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d3a1c2b4e5f6"
down_revision: str | Sequence[str] | None = "4d2403b3a9ac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("threads", schema=None) as batch_op:
        batch_op.drop_index("ix_thread_collection_id")
        batch_op.drop_constraint("fk_threads_collection_id_collections", type_="foreignkey")
        batch_op.drop_column("collection_id")
    op.drop_index("ix_collections_user_id", table_name="collections")
    op.drop_index(
        "uq_collections_user_default",
        table_name="collections",
        postgresql_where=sa.text("is_default = TRUE"),
    )
    op.drop_table("collections")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table(
        "collections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("threads", schema=None) as batch_op:
        batch_op.add_column(sa.Column("collection_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_threads_collection_id_collections",
            "collections",
            ["collection_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_thread_collection_id", ["collection_id"])
    op.create_index("ix_collections_user_id", "collections", ["user_id"])
    op.create_index(
        "uq_collections_user_default",
        "collections",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_default = TRUE"),
    )

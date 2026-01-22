"""add auth user fields and revoked tokens

Revision ID: e98747c899c0
Revises: a1b2c3d4e5f6
Create Date: 2026-01-18 18:54:40.378125

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e98747c899c0"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Check if columns already exist before adding
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    users_columns = [c["name"] for c in inspector.get_columns("users")]

    if "email" not in users_columns:
        with op.batch_alter_table("users") as batch_op:
            batch_op.add_column(sa.Column("email", sa.String(length=255), nullable=True))
    if "password_hash" not in users_columns:
        with op.batch_alter_table("users") as batch_op:
            batch_op.add_column(sa.Column("password_hash", sa.String(length=255), nullable=True))
    if "is_admin" not in users_columns:
        with op.batch_alter_table("users") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "is_admin",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )

    # Check if constraint already exists
    constraints = inspector.get_unique_constraints("users")
    if not any(c["name"] == "uq_users_email" for c in constraints):
        with op.batch_alter_table("users") as batch_op:
            batch_op.create_unique_constraint("uq_users_email", ["email"])

    # Create revoked_tokens table if not exists
    tables = inspector.get_table_names()
    if "revoked_tokens" not in tables:
        op.create_table(
            "revoked_tokens",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("jti", sa.String(length=64), nullable=False),
            sa.Column(
                "revoked_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["users.id"],
                name="fk_revoked_tokens_user_id_users",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_revoked_tokens"),
            sa.UniqueConstraint("jti", name="uq_revoked_tokens_jti"),
        )
        op.create_index("ix_revoked_tokens_user_id", "revoked_tokens", ["user_id"])
        op.create_index("ix_revoked_tokens_expires_at", "revoked_tokens", ["expires_at"])


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # Drop indexes and table if they exist
    indexes = inspector.get_indexes("revoked_tokens")
    index_names = [i["name"] for i in indexes]
    if "ix_revoked_tokens_expires_at" in index_names:
        op.drop_index("ix_revoked_tokens_expires_at", table_name="revoked_tokens")
    if "ix_revoked_tokens_user_id" in index_names:
        op.drop_index("ix_revoked_tokens_user_id", table_name="revoked_tokens")

    tables = inspector.get_table_names()
    if "revoked_tokens" in tables:
        op.drop_table("revoked_tokens")

    # Drop constraint and columns if they exist
    constraints = inspector.get_unique_constraints("users")
    if any(c["name"] == "uq_users_email" for c in constraints):
        with op.batch_alter_table("users") as batch_op:
            batch_op.drop_constraint("uq_users_email", type_="unique")

    columns = inspector.get_columns("users")
    column_names = [c["name"] for c in columns]
    if "is_admin" in column_names:
        with op.batch_alter_table("users") as batch_op:
            batch_op.drop_column("is_admin")
    if "password_hash" in column_names:
        with op.batch_alter_table("users") as batch_op:
            batch_op.drop_column("password_hash")
    if "email" in column_names:
        with op.batch_alter_table("users") as batch_op:
            batch_op.drop_column("email")

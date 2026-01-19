"""add auth user fields and revoked tokens

Revision ID: e98747c899c0
Revises: a1b2c3d4e5f6
Create Date: 2026-01-18 18:54:40.378125

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e98747c899c0"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Apply schema changes to add authentication fields to the users table and create a revoked_tokens table for tracking revoked tokens.
    
    Adds nullable `email` and `password_hash` columns and a non-nullable `is_admin` boolean (default `false`) to `users`, with a unique constraint on `email`. Creates `revoked_tokens` with an integer primary key `id`, `user_id` (foreign key to `users.id` with ON DELETE CASCADE), unique `jti`, timezone-aware `revoked_at` (default CURRENT_TIMESTAMP), `expires_at`, and indexes on `user_id` and `expires_at`.
    """
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("email", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("password_hash", sa.String(length=255), nullable=True))
        batch_op.add_column(
            sa.Column(
                "is_admin",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.create_unique_constraint("uq_users_email", ["email"])

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
    """
    Revert the schema changes introduced by this migration.
    
    Drops the revoked_tokens table and its indexes, removes the unique constraint on users.email, and drops the users columns added by the upgrade (email, password_hash, is_admin).
    """
    op.drop_index("ix_revoked_tokens_expires_at", table_name="revoked_tokens")
    op.drop_index("ix_revoked_tokens_user_id", table_name="revoked_tokens")
    op.drop_table("revoked_tokens")

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("uq_users_email", type_="unique")
        batch_op.drop_column("is_admin")
        batch_op.drop_column("password_hash")
        batch_op.drop_column("email")
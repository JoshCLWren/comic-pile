from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "c2f66bf43d9f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "postgresql":
        op.execute("ALTER TABLE sessions DROP CONSTRAINT IF EXISTS sessions_pending_thread_id_fkey")
        op.execute(
            "ALTER TABLE sessions ADD CONSTRAINT sessions_pending_thread_id_fkey "
            "FOREIGN KEY (pending_thread_id) REFERENCES threads(id) ON DELETE SET NULL"
        )
    elif dialect == "sqlite":
        with op.batch_alter_table("sessions", schema=None) as batch_op:
            batch_op.drop_constraint("sessions_pending_thread_id_fkey", type_="foreignkey")
            batch_op.create_foreign_key(
                "sessions_pending_thread_id_fkey",
                "threads",
                ["pending_thread_id"],
                ["id"],
                ondelete="SET NULL",
            )


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "postgresql":
        op.execute("ALTER TABLE sessions DROP CONSTRAINT IF EXISTS sessions_pending_thread_id_fkey")
        op.execute(
            "ALTER TABLE sessions ADD CONSTRAINT sessions_pending_thread_id_fkey "
            "FOREIGN KEY (pending_thread_id) REFERENCES threads(id)"
        )
    elif dialect == "sqlite":
        with op.batch_alter_table("sessions", schema=None) as batch_op:
            batch_op.drop_constraint("sessions_pending_thread_id_fkey", type_="foreignkey")
            batch_op.create_foreign_key(
                "sessions_pending_thread_id_fkey",
                "threads",
                ["pending_thread_id"],
                ["id"],
                ondelete="NO ACTION",
            )

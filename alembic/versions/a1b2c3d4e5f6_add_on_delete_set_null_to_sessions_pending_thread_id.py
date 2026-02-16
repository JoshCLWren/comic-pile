"""Set sessions.pending_thread_id FK ON DELETE behavior."""

from collections.abc import Sequence

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "c2f66bf43d9f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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

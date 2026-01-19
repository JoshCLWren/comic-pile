"""normalize sessions pending_thread fk

Revision ID: dd6f892e4e04
Revises: e98747c899c0
Create Date: 2026-01-18 19:56:23.920240

"""

from typing import Protocol, Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import Connection


# revision identifiers, used by Alembic.
revision: str = "dd6f892e4e04"
down_revision: Union[str, Sequence[str], None] = "e98747c899c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SESSIONS_PENDING_THREAD_FK_NAMES: tuple[str, ...] = (
    "fk_sessions_pending_thread_id_threads",
    "sessions_pending_thread_id_fkey",
)


def _fk_exists(conn: Connection, table_name: str, constraint_name: str) -> bool:
    inspector = sa.inspect(conn)
    fks = inspector.get_foreign_keys(table_name)
    return any(fk.get("name") == constraint_name for fk in fks)


class _BatchOp(Protocol):
    def drop_constraint(self, constraint_name: str, type_: str | None = None) -> None: ...


def _sqlite_safe_drop_fk(
    batch_op: _BatchOp,
    conn: Connection,
    table_name: str,
    constraint_name: str,
) -> None:
    if _fk_exists(conn, table_name, constraint_name):
        batch_op.drop_constraint(constraint_name, type_="foreignkey")


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "postgresql":
        for name in _SESSIONS_PENDING_THREAD_FK_NAMES:
            op.execute(f"ALTER TABLE sessions DROP CONSTRAINT IF EXISTS {name}")

        op.execute(
            "ALTER TABLE sessions ADD CONSTRAINT sessions_pending_thread_id_fkey "
            "FOREIGN KEY (pending_thread_id) REFERENCES threads(id) ON DELETE SET NULL"
        )
        return

    if dialect == "sqlite":
        with op.batch_alter_table("sessions", schema=None) as batch_op:
            for name in _SESSIONS_PENDING_THREAD_FK_NAMES:
                _sqlite_safe_drop_fk(batch_op, conn, "sessions", name)

            batch_op.create_foreign_key(
                "sessions_pending_thread_id_fkey",
                "threads",
                ["pending_thread_id"],
                ["id"],
                ondelete="SET NULL",
            )
        return

    for name in _SESSIONS_PENDING_THREAD_FK_NAMES:
        if _fk_exists(conn, "sessions", name):
            op.drop_constraint(name, "sessions", type_="foreignkey")

    op.create_foreign_key(
        "sessions_pending_thread_id_fkey",
        "sessions",
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
        for name in _SESSIONS_PENDING_THREAD_FK_NAMES:
            op.execute(f"ALTER TABLE sessions DROP CONSTRAINT IF EXISTS {name}")

        op.execute(
            "ALTER TABLE sessions ADD CONSTRAINT sessions_pending_thread_id_fkey "
            "FOREIGN KEY (pending_thread_id) REFERENCES threads(id)"
        )
        return

    if dialect == "sqlite":
        with op.batch_alter_table("sessions", schema=None) as batch_op:
            for name in _SESSIONS_PENDING_THREAD_FK_NAMES:
                _sqlite_safe_drop_fk(batch_op, conn, "sessions", name)

            batch_op.create_foreign_key(
                "sessions_pending_thread_id_fkey",
                "threads",
                ["pending_thread_id"],
                ["id"],
                ondelete="NO ACTION",
            )
        return

    for name in _SESSIONS_PENDING_THREAD_FK_NAMES:
        if _fk_exists(conn, "sessions", name):
            op.drop_constraint(name, "sessions", type_="foreignkey")

    op.create_foreign_key(
        "sessions_pending_thread_id_fkey",
        "sessions",
        "threads",
        ["pending_thread_id"],
        ["id"],
    )

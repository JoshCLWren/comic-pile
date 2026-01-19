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
    """
    Checks whether a foreign key constraint with the given name exists on the specified table.
    
    Parameters:
    	conn (Connection): Active SQLAlchemy connection.
    	table_name (str): Name of the table to inspect.
    	constraint_name (str): Name of the foreign key constraint to look for.
    
    Returns:
    	`true` if a foreign key with `constraint_name` exists on `table_name`, `false` otherwise.
    """
    inspector = sa.inspect(conn)
    fks = inspector.get_foreign_keys(table_name)
    return any(fk.get("name") == constraint_name for fk in fks)


class _BatchOp(Protocol):
    def drop_constraint(self, constraint_name: str, type_: str | None = None) -> None: """
Remove a named constraint from the table being altered in this batch operation.

Parameters:
	constraint_name (str): The exact name of the constraint to drop.
	type_ (str | None): Optional category of the constraint (for example "foreignkey" or "unique") when required by the database backend; if omitted, the backend will attempt to infer the type.
"""
...


def _sqlite_safe_drop_fk(
    batch_op: _BatchOp,
    conn: Connection,
    table_name: str,
    constraint_name: str,
) -> None:
    """
    Drop the specified foreign key constraint from a SQLite table using the provided batch operation if the constraint exists.
    
    Parameters:
        batch_op (_BatchOp): Batch alter-table operation providing drop_constraint().
        conn (Connection): Active database connection used to inspect existing constraints.
        table_name (str): Name of the table containing the foreign key.
        constraint_name (str): Name of the foreign key constraint to drop.
    """
    if _fk_exists(conn, table_name, constraint_name):
        batch_op.drop_constraint(constraint_name, type_="foreignkey")


def upgrade() -> None:
    """
    Normalize the foreign key on sessions.pending_thread_id to reference threads(id) with ON DELETE SET NULL.
    
    On PostgreSQL this drops any known legacy constraints and adds a single constraint named
    sessions_pending_thread_id_fkey with ON DELETE SET NULL. On SQLite it safely drops existing
    constraints using a batch operation and creates the same constraint with ON DELETE SET NULL.
    On other dialects it drops any known legacy constraints if present and creates the
    sessions_pending_thread_id_fkey constraint with ON DELETE SET NULL.
    """
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
    """
    Revert the sessions.pending_thread_id foreign key to its previous database-specific configuration.
    
    Per dialect behavior:
    - PostgreSQL: drops any known constraints for sessions.pending_thread_id and re-adds the foreign key constraint named `sessions_pending_thread_id_fkey` referencing threads(id) using the database default ON DELETE behavior.
    - SQLite: drops any known constraints via a batch alter and creates `sessions_pending_thread_id_fkey` referencing threads(id) with ON DELETE NO ACTION.
    - Other dialects: drops any known constraints if present and recreates `sessions_pending_thread_id_fkey` referencing threads(id) without an explicit ON DELETE clause.
    """
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
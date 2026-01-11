"""add_cascade_delete_to_events_thread_id

Revision ID: f5g9b0c3d4e2
Revises: e4f8a9b2c3d1
Create Date: 2026-01-11 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f5g9b0c3d4e2"
down_revision: Union[str, Sequence[str], None] = "e4f8a9b2c3d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "postgresql":
        op.execute("ALTER TABLE events DROP CONSTRAINT IF EXISTS events_thread_id_fkey")
        op.execute(
            "ALTER TABLE events ADD CONSTRAINT events_thread_id_fkey "
            "FOREIGN KEY (thread_id) REFERENCES threads(id) ON DELETE CASCADE"
        )
    elif dialect == "sqlite":
        with op.batch_alter_table("events", schema=None) as batch_op:
            batch_op.drop_constraint("events_thread_id_fkey", type_="foreignkey")
            batch_op.create_foreign_key(
                "events_thread_id_fkey",
                "threads",
                ["thread_id"],
                ["id"],
                ondelete="CASCADE",
            )


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "postgresql":
        op.execute("ALTER TABLE events DROP CONSTRAINT IF EXISTS events_thread_id_fkey")
        op.execute(
            "ALTER TABLE events ADD CONSTRAINT events_thread_id_fkey "
            "FOREIGN KEY (thread_id) REFERENCES threads(id)"
        )
    elif dialect == "sqlite":
        with op.batch_alter_table("events", schema=None) as batch_op:
            batch_op.drop_constraint("events_thread_id_fkey", type_="foreignkey")
            batch_op.create_foreign_key(
                "events_thread_id_fkey",
                "threads",
                ["thread_id"],
                ["id"],
                ondelete="NO ACTION",
            )

"""add_cascade_delete_to_snapshots_event_id

Revision ID: e4f8a9b2c3d1
Revises: c2f66bf43d9f
Create Date: 2026-01-11 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite


# revision identifiers, used by Alembic.
revision: str = "e4f8a9b2c3d1"
down_revision: Union[str, Sequence[str], None] = "c2f66bf43d9f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "postgresql":
        op.execute("ALTER TABLE snapshots DROP CONSTRAINT IF EXISTS snapshots_event_id_fkey")
        op.execute(
            "ALTER TABLE snapshots ADD CONSTRAINT snapshots_event_id_fkey "
            "FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE"
        )
    elif dialect == "sqlite":
        with op.batch_alter_table("snapshots", schema=None) as batch_op:
            batch_op.drop_constraint("snapshots_event_id_fkey", type_="foreignkey")
            batch_op.create_foreign_key(
                "snapshots_event_id_fkey",
                "events",
                ["event_id"],
                ["id"],
                ondelete="CASCADE",
            )


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "postgresql":
        op.execute("ALTER TABLE snapshots DROP CONSTRAINT IF EXISTS snapshots_event_id_fkey")
        op.execute(
            "ALTER TABLE snapshots ADD CONSTRAINT snapshots_event_id_fkey "
            "FOREIGN KEY (event_id) REFERENCES events(id)"
        )
    elif dialect == "sqlite":
        with op.batch_alter_table("snapshots", schema=None) as batch_op:
            batch_op.drop_constraint("snapshots_event_id_fkey", type_="foreignkey")
            batch_op.create_foreign_key(
                "snapshots_event_id_fkey",
                "events",
                ["event_id"],
                ["id"],
                ondelete="NO ACTION",
            )

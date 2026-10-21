"""Index the shared CBL catalog for folder browsing and name/path search.

Revision ID: c40080000001
Revises: q4m500000001
Create Date: 2026-10-21 00:00:00.000000

Issue #4008: folder navigation filters active rows by a source-path prefix and
catalog search matches substrings of ``name`` / ``source_path``. The btree
prefix index keeps folder scoping index-eligible; the trigram GIN indexes keep
case-insensitive substring search from degrading into an unbounded sequential
scan as the full fork is indexed.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c40080000001"
down_revision: str | Sequence[str] | None = "q4m500000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add prefix and trigram indexes for shared catalog browsing.

    Args: None
    Returns: None
    """
    op.create_index(
        "ix_cbl_source_list_active_path",
        "cbl_source_lists",
        ["active", "source_path"],
        postgresql_ops={"source_path": "text_pattern_ops"},
    )
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_index(
        "ix_cbl_source_list_name_trgm",
        "cbl_source_lists",
        ["name"],
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_cbl_source_list_source_path_trgm",
        "cbl_source_lists",
        ["source_path"],
        postgresql_using="gin",
        postgresql_ops={"source_path": "gin_trgm_ops"},
    )


def downgrade() -> None:
    """Remove the catalog browsing indexes.

    ``pg_trgm`` is intentionally left installed: it is a database-wide extension
    that another revision or consumer may rely on.

    Args: None
    Returns: None
    """
    op.drop_index("ix_cbl_source_list_source_path_trgm", table_name="cbl_source_lists")
    op.drop_index("ix_cbl_source_list_name_trgm", table_name="cbl_source_lists")
    op.drop_index("ix_cbl_source_list_active_path", table_name="cbl_source_lists")

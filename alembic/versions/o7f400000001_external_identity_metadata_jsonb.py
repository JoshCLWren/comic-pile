"""Store external identity metadata as jsonb.

Revision ID: o7f400000001
Revises: f2a3b4c5d6e7
Create Date: 2026-10-12 00:00:00.000000

Issue #3387: ``GET /api/v1/creators/summaries`` completed in 1914.75 ms against
a 1000 ms budget, with ``db;dur=1438.88;desc="4 queries"``.

Root cause, measured with ``EXPLAIN ANALYZE`` against a library of 2000 owned
issues carrying real normalized ComicVine payloads (~16 kB per document):

    external_identities.metadata_json -> 'creator_credits'   80.96 ms
    every other statement in the request                     <= 1 ms each

``metadata_json`` was a PostgreSQL ``json`` column, which stores the provider
document as raw text. Every operator on it is therefore a parse of the whole
document rather than a key lookup, so one creator read reparsed the retained
``raw_provider_payload`` of every owned issue -- bytes the reader never looks at.
The cost grew with library size times payload size, which is why a mature
account spent its entire database budget there.

``jsonb`` parses the document once, at write time, and turns the same projection
into a lookup: the same statement measures 16.35 ms. Nothing else about the
read changes, and no stored value is semantically lost -- the cast only
normalizes whitespace, key order, and duplicate object keys.

This is deliberately the only change. A narrow stored ``creator_credits``
generated column would take the statement to 1.71 ms by also skipping the TOAST
detoast of the payload, but it costs a second full-table rewrite and a
``drop_column`` on the way back down, and the measured jsonb conversion alone
already returns the route to roughly 40% headroom under its budget.

Readers that rely on jsonb operators keep working unchanged:
``app/services/comicvine_intelligence.py`` already casts this column to
``jsonb`` for its containment queries, and the expression GIN index created by
``c84700000001`` follows the column through the type change, so those queries
keep resolving to the same index.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "o7f400000001"
down_revision: str | Sequence[str] | None = "f2a3b4c5d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Convert the provider metadata column to ``jsonb``.

    Returns:
        None.
    """
    op.execute(
        """
        ALTER TABLE external_identities
            ALTER COLUMN metadata_json TYPE jsonb USING metadata_json::jsonb
        """
    )


#: Name of the expression GIN index created by ``c84700000001``.
#: PostgreSQL simplifies ``((metadata_json::jsonb) jsonb_path_ops)`` to
#: ``(metadata_metadata jsonb_path_ops)`` when the column becomes ``jsonb``,
#: because the cast is then redundant. That simplification is what makes a
#: naive re-type fail on the way down: the rebuilt expression would be a plain
#: ``json`` column fed to a ``jsonb`` operator class. The downgrade therefore
#: restores the original cast expression explicitly.
CONTENT_GIN_INDEX = "ix_external_identity_metadata_jsonb_path"


def downgrade() -> None:
    """Convert the provider metadata column back to text ``json``.

    PostgreSQL has an assignment cast in both directions, so no ``USING`` clause
    is needed and the column keeps its stored values. The containment index is
    dropped and recreated around the re-type so it ends up byte-for-byte the
    expression index ``c84700000001`` created.

    Returns:
        None.
    """
    op.drop_index(CONTENT_GIN_INDEX, table_name="external_identities")
    op.execute(
        """
        ALTER TABLE external_identities
            ALTER COLUMN metadata_json TYPE json
        """
    )
    op.execute(
        f"""
        CREATE INDEX {CONTENT_GIN_INDEX}
            ON external_identities
            USING gin ((metadata_json::jsonb) jsonb_path_ops)
        """
    )

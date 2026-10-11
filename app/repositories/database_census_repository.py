"""PostgreSQL storage, index, and query-census persistence.

This repository owns every SQL statement used by the database census command
(issue #3217). ``DatabaseCensusService`` orchestrates; it must not build or
execute queries itself.

All work runs inside a caller-managed ``READ ONLY`` transaction with a bounded
``statement_timeout`` so an explicitly supplied database can never be mutated
or scanned without bound.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Row, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Base

from app.models import (
    CBLSource,
    CBLSourceEntry,
    CBLSourceList,
    CatalogCommitReceipt,
    ContinuityPlan,
    ContinuityRule,
    CustomCBLEntry,
    CustomCBLList,
    Dependency,
    DependencyGroup,
    DependencyGroupMembership,
    DeliveryRecord,
    Event,
    ExternalIdentity,
    FailedLoginAttempt,
    Issue,
    IssueExternalIdentityMapping,
    IssueMetadataCorrection,
    PerformanceMetric,
    ReadingOrder,
    ReadingOrderItem,
    ReadingPlanDependency,
    ReadingPlanIssue,
    ReadingPlanReleaseSource,
    ReadingPlanSource,
    ReadingPlanSourcePlacement,
    Release,
    RevokedToken,
    ReadingSession,
    Snapshot,
    Tag,
    TagAssignment,
    TasteSignal,
    Thread,
    ThreadExternalSeriesMapping,
    User,
    UserPreferences,
)
from app.models.password_reset_token import PasswordResetToken


#: Tables inventoried by the census, paired with their ORM model so the exact
#: row count and the planner estimate can be compared per table.
CENSUS_TABLE_MODELS: tuple[tuple[str, type[Base]], ...] = (
    ("users", User),
    ("threads", Thread),
    ("issues", Issue),
    ("events", Event),
    ("snapshots", Snapshot),
    ("sessions", ReadingSession),
    ("external_identities", ExternalIdentity),
    ("issue_external_identity_mappings", IssueExternalIdentityMapping),
    ("thread_external_series_mappings", ThreadExternalSeriesMapping),
    ("tags", Tag),
    ("tag_assignments", TagAssignment),
    ("custom_cbl_entries", CustomCBLEntry),
    ("custom_cbl_lists", CustomCBLList),
    ("continuity_plans", ContinuityPlan),
    ("continuity_rules", ContinuityRule),
    ("dependencies", Dependency),
    ("dependency_groups", DependencyGroup),
    ("dependency_group_memberships", DependencyGroupMembership),
    ("reading_plan_issues", ReadingPlanIssue),
    ("reading_plan_dependencies", ReadingPlanDependency),
    ("reading_plan_sources", ReadingPlanSource),
    ("reading_plan_source_placements", ReadingPlanSourcePlacement),
    ("reading_plan_release_sources", ReadingPlanReleaseSource),
    ("releases", Release),
    ("issue_metadata_corrections", IssueMetadataCorrection),
    ("password_reset_tokens", PasswordResetToken),
    ("revoked_tokens", RevokedToken),
    ("failed_login_attempts", FailedLoginAttempt),
    ("user_preferences", UserPreferences),
    ("taste_signals", TasteSignal),
    ("reading_orders", ReadingOrder),
    ("reading_order_items", ReadingOrderItem),
    ("cbl_sources", CBLSource),
    ("cbl_source_lists", CBLSourceList),
    ("cbl_source_entries", CBLSourceEntry),
    ("catalog_commit_receipts", CatalogCommitReceipt),
    ("delivery_records", DeliveryRecord),
    ("performance_metrics", PerformanceMetric),
)

#: Catalog query returning one row per index, including the predicate, key
#: columns, uniqueness, constraint backing, and deferrability the issue
#: contract requires for redundancy reasoning.
INDEX_CATALOG_SQL = """
SELECT
    ns.nspname AS schema_name,
    tbl.relname AS table_name,
    idx_cls.relname AS index_name,
    idx.indisunique AS is_unique,
    idx.indisprimary AS is_primary,
    (idx.indpred IS NOT NULL) AS is_partial,
    pg_get_expr(idx.indpred, idx.indrelid) AS predicate,
    (idx.indexprs IS NOT NULL) AS has_expressions,
    am.amname AS access_method,
    pg_get_indexdef(idx.indexrelid) AS definition,
    pg_relation_size(idx.indexrelid) AS size_bytes,
    pg_size_pretty(pg_relation_size(idx.indexrelid)) AS size_pretty,
    COALESCE(stats.idx_scan, 0) AS scans,
    COALESCE(stats.idx_tup_read, 0) AS tuples_read,
    COALESCE(stats.idx_tup_fetch, 0) AS tuples_fetched,
    con.conname AS constraint_name,
    con.contype::text AS constraint_type,
    COALESCE(con.condeferrable, false) AS constraint_deferrable,
    COALESCE(con.condeferred, false) AS constraint_deferred,
    ARRAY(
        SELECT att.attname
        FROM pg_attribute att
        WHERE att.attrelid = idx.indrelid
          AND att.attnum = ANY(idx.indkey)
        ORDER BY array_position(idx.indkey::smallint[], att.attnum)
    ) AS key_columns
FROM pg_index idx
JOIN pg_class idx_cls ON idx_cls.oid = idx.indexrelid
JOIN pg_class tbl ON tbl.oid = idx.indrelid
JOIN pg_namespace ns ON ns.oid = tbl.relnamespace
JOIN pg_am am ON am.oid = idx_cls.relam
LEFT JOIN pg_stat_user_indexes stats ON stats.indexrelid = idx.indexrelid
LEFT JOIN pg_constraint con ON con.conindid = idx.indexrelid
WHERE ns.nspname = 'public'
ORDER BY tbl.relname, idx_cls.relname
"""

#: Storage inventory: table bytes reported separately from the planner's row
#: estimate so byte measurements are never confused with row estimates.
TABLE_STORAGE_SQL = """
SELECT
    schemaname AS schema_name,
    tablename AS table_name,
    pg_total_relation_size(format('%I.%I', schemaname, tablename)) AS total_bytes,
    pg_relation_size(format('%I.%I', schemaname, tablename)) AS table_bytes,
    pg_total_relation_size(format('%I.%I', schemaname, tablename))
        - pg_relation_size(format('%I.%I', schemaname, tablename)) AS index_bytes,
    pg_size_pretty(pg_total_relation_size(format('%I.%I', schemaname, tablename))) AS total_pretty,
    pg_size_pretty(pg_relation_size(format('%I.%I', schemaname, tablename))) AS table_pretty,
    pg_size_pretty(
        pg_total_relation_size(format('%I.%I', schemaname, tablename))
        - pg_relation_size(format('%I.%I', schemaname, tablename))
    ) AS index_pretty
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY total_bytes DESC
"""

#: TOAST storage per table. TOAST relations are named ``pg_toast_<oid>``, so
#: they are reached through ``pg_class.reltoastrelid`` rather than by guessing
#: a child relation name.
TOAST_STORAGE_SQL = """
SELECT
    ns.nspname AS schema_name,
    tbl.relname AS table_name,
    pg_total_relation_size(tbl.reltoastrelid) AS toast_bytes,
    pg_size_pretty(pg_total_relation_size(tbl.reltoastrelid)) AS toast_pretty
FROM pg_class tbl
JOIN pg_namespace ns ON ns.oid = tbl.relnamespace
WHERE ns.nspname = 'public'
  AND tbl.relkind = 'r'
  AND tbl.reltoastrelid <> 0
  AND pg_total_relation_size(tbl.reltoastrelid) > 0
ORDER BY toast_bytes DESC
"""

#: Planner row estimate for a table, reported next to (never instead of) the
#: exact count so estimates and measurements stay distinguishable.
ROW_ESTIMATE_SQL = """
SELECT reltuples::bigint
FROM pg_class
WHERE relname = :table_name
  AND relnamespace = 'public'::regnamespace
"""

#: Snapshot payload distribution grouped by the payload schema version stored
#: inside ``thread_states``.
SNAPSHOT_VERSION_SQL = """
SELECT
    thread_states ->> 'version' AS version,
    COUNT(*) AS row_count,
    AVG(octet_length(thread_states::text))::bigint AS avg_payload_bytes,
    MAX(octet_length(thread_states::text))::bigint AS max_payload_bytes,
    MIN(octet_length(thread_states::text))::bigint AS min_payload_bytes,
    SUM(octet_length(thread_states::text))::bigint AS total_payload_bytes
FROM snapshots
GROUP BY thread_states ->> 'version'
ORDER BY row_count DESC
"""

#: Snapshot counts split by whether a session-state payload is present.
SNAPSHOT_SESSION_STATE_SQL = """
SELECT
    COUNT(*) AS total_snapshots,
    COUNT(DISTINCT session_id) AS distinct_sessions,
    COUNT(*) FILTER (WHERE session_state IS NOT NULL) AS snapshots_with_session_state,
    COUNT(*) FILTER (WHERE session_state IS NULL) AS snapshots_without_session_state,
    COALESCE(
        AVG(octet_length(session_state::text)) FILTER (WHERE session_state IS NOT NULL),
        0
    )::bigint AS avg_session_state_bytes
FROM snapshots
"""

#: Largest snapshot payloads, used only to size growth. No payload content is
#: ever selected, so no user data can leak through this query.
SNAPSHOT_PAYLOAD_GROWTH_SQL = """
SELECT
    COUNT(*) AS snapshot_rows,
    COALESCE(SUM(octet_length(thread_states::text)), 0)::bigint AS total_thread_state_bytes,
    COALESCE(MAX(octet_length(thread_states::text)), 0)::bigint AS max_thread_state_bytes,
    COALESCE(SUM(octet_length(session_state::text)), 0)::bigint AS total_session_state_bytes
FROM snapshots
WHERE session_id = :session_id
"""

#: Undo growth for the newest snapshot of a bounded set of reading sessions:
#: rows touched and payload bytes the latest undo has to restore.
LATEST_UNDO_GROWTH_SQL = """
SELECT
    s.session_id AS session_id,
    (SELECT COUNT(*) FROM snapshots inner_s WHERE inner_s.session_id = s.session_id)
        AS session_snapshot_rows,
    octet_length(s.thread_states::text) AS thread_state_bytes,
    COALESCE(octet_length(s.session_state::text), 0) AS session_state_bytes,
    e.type AS event_type,
    e.die AS die,
    e.die_after AS die_after
FROM snapshots s
LEFT JOIN events e ON e.id = s.event_id
WHERE s.session_id = ANY(:session_ids)
ORDER BY s.created_at DESC, s.id DESC
"""

#: Reorder growth for the newest queue-move events of a bounded set of readers.
#: Only row counts and byte sizes are reported; no reorder payload is emitted.
REORDER_GROWTH_SQL = """
SELECT
    COUNT(*) AS reorder_event_rows,
    COUNT(DISTINCT e.thread_id) AS distinct_threads_moved,
    COALESCE(SUM(octet_length(COALESCE(e.queue_move, ''))), 0)::bigint AS queue_move_bytes
FROM events e
WHERE e.type = 'reorder'
  AND e.session_id = ANY(:session_ids)
"""

#: Primary key inventory.
PRIMARY_KEY_SQL = """
SELECT
    tbl.relname AS table_name,
    con.conname AS constraint_name,
    att.attname AS column_name,
    ARRAY(
        SELECT att2.attname
        FROM unnest(con.conkey) WITH ORDINALITY AS keys(attnum, ordinal)
        JOIN pg_attribute att2 ON att2.attrelid = con.conrelid AND att2.attnum = keys.attnum
        ORDER BY keys.ordinal
    ) AS key_columns,
    con.condeferrable AS is_deferrable,
    con.condeferred AS is_deferred
FROM pg_constraint con
JOIN pg_class tbl ON tbl.oid = con.conrelid
JOIN pg_namespace ns ON ns.oid = tbl.relnamespace
JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS first_key(attnum, ordinal)
    ON first_key.ordinal = 1
JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = first_key.attnum
WHERE con.contype = 'p' AND ns.nspname = 'public'
ORDER BY tbl.relname, con.conname
"""

#: Foreign key inventory.
FOREIGN_KEY_SQL = """
SELECT
    child_tbl.relname AS table_name,
    con.conname AS constraint_name,
    child_att.attname AS column_name,
    parent_tbl.relname AS references_table,
    parent_att.attname AS references_column,
    con.condeferrable AS is_deferrable,
    con.condeferred AS is_deferred,
    con.confdeltype::text AS on_delete,
    con.confupdtype::text AS on_update
FROM pg_constraint con
JOIN pg_class child_tbl ON child_tbl.oid = con.conrelid
JOIN pg_namespace ns ON ns.oid = child_tbl.relnamespace
JOIN pg_class parent_tbl ON parent_tbl.oid = con.confrelid
JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS ck(attnum, ordinal)
    ON ck.ordinal = 1
JOIN LATERAL unnest(con.confkey) WITH ORDINALITY AS pk(attnum, ordinal)
    ON pk.ordinal = ck.ordinal
JOIN pg_attribute child_att
    ON child_att.attrelid = con.conrelid AND child_att.attnum = ck.attnum
JOIN pg_attribute parent_att
    ON parent_att.attrelid = con.confrelid AND parent_att.attnum = pk.attnum
WHERE con.contype = 'f' AND ns.nspname = 'public'
ORDER BY child_tbl.relname, con.conname
"""

#: Unique constraint inventory (unique indexes that back a constraint).
UNIQUE_CONSTRAINT_SQL = """
SELECT
    tbl.relname AS table_name,
    con.conname AS constraint_name,
    att.attname AS column_name,
    ARRAY(
        SELECT att2.attname
        FROM unnest(con.conkey) WITH ORDINALITY AS keys(attnum, ordinal)
        JOIN pg_attribute att2 ON att2.attrelid = con.conrelid AND att2.attnum = keys.attnum
        ORDER BY keys.ordinal
    ) AS key_columns,
    con.condeferrable AS is_deferrable,
    con.condeferred AS is_deferred
FROM pg_constraint con
JOIN pg_class tbl ON tbl.oid = con.conrelid
JOIN pg_namespace ns ON ns.oid = tbl.relnamespace
JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS first_key(attnum, ordinal)
    ON first_key.ordinal = 1
JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = first_key.attnum
WHERE con.contype = 'u' AND ns.nspname = 'public'
ORDER BY tbl.relname, con.conname
"""

#: Reader ids used only to pick bounded, representative samples. The service
#: drops these identifiers before the report is emitted.
SAMPLE_READER_IDS_SQL = """
SELECT rs.user_id AS user_id
FROM snapshots s
JOIN sessions rs ON rs.id = s.session_id
GROUP BY rs.user_id
ORDER BY COUNT(*) DESC, rs.user_id
LIMIT :sample_limit
"""


def _row_to_dict(row: Row[tuple[object, ...]]) -> dict[str, Any]:
    """Convert a result row into a plain dictionary.

    Args:
        row: A SQLAlchemy ``Row`` mapping.

    Returns:
        Plain dictionary copy of the row.
    """
    return dict(row._mapping)


class DatabaseCensusRepository:
    """Owns every SQL statement executed by the database census."""

    def __init__(self, db: AsyncSession):
        """Initialize the repository.

        Args:
            db: Async database session.
        """
        self.db = db

    async def begin_read_only_transaction(
        self,
        statement_timeout_seconds: int,
        lock_timeout_seconds: int = 1,
    ) -> None:
        """Open a fresh transaction that cannot write and cannot run forever.

        Args:
            statement_timeout_seconds: Maximum wall-clock seconds per statement.
            lock_timeout_seconds: Maximum seconds to wait for a lock.

        Raises:
            ValueError: If either timeout is not a positive integer.
        """
        if statement_timeout_seconds <= 0 or lock_timeout_seconds <= 0:
            raise ValueError("census timeouts must be positive integers")
        if self.db.in_transaction():
            await self.db.rollback()
        await self.db.begin()
        await self.db.execute(text("SET TRANSACTION READ ONLY"))
        await self.db.execute(
            text(f"SET LOCAL statement_timeout = {int(statement_timeout_seconds) * 1000}")
        )
        await self.db.execute(text(f"SET LOCAL lock_timeout = {int(lock_timeout_seconds) * 1000}"))
        await self.db.execute(
            text("SET LOCAL idle_in_transaction_session_timeout = 60000")
        )

    async def rollback(self) -> None:
        """Discard any open census transaction."""
        if self.db.in_transaction():
            await self.db.rollback()

    async def postgresql_version(self) -> str:
        """Return the server version string."""
        result = await self.db.execute(text("SELECT version()"))
        return str(result.scalar_one() or "unknown")

    async def table_storage(self) -> list[dict[str, Any]]:
        """Return measured storage bytes per table."""
        result = await self.db.execute(text(TABLE_STORAGE_SQL))
        return [_row_to_dict(row) for row in result.fetchall()]

    async def toast_storage(self) -> list[dict[str, Any]]:
        """Return measured TOAST storage bytes per table."""
        result = await self.db.execute(text(TOAST_STORAGE_SQL))
        return [_row_to_dict(row) for row in result.fetchall()]

    async def exact_row_count(self, model: type[Base]) -> int:
        """Return the exact row count for a mapped table."""
        result = await self.db.execute(select(func.count()).select_from(model))
        return int(result.scalar() or 0)

    async def estimated_row_count(self, table_name: str) -> int:
        """Return the planner's row estimate for a table."""
        result = await self.db.execute(
            text(ROW_ESTIMATE_SQL), {"table_name": table_name}
        )
        return int(result.scalar() or 0)

    async def index_catalog(self) -> list[dict[str, Any]]:
        """Return the full index catalog with constraint and predicate detail."""
        result = await self.db.execute(text(INDEX_CATALOG_SQL))
        return [_row_to_dict(row) for row in result.fetchall()]

    async def snapshot_version_distribution(self) -> list[dict[str, Any]]:
        """Return snapshot payload size distribution grouped by payload version."""
        result = await self.db.execute(text(SNAPSHOT_VERSION_SQL))
        return [_row_to_dict(row) for row in result.fetchall()]

    async def snapshot_session_state_summary(self) -> dict[str, Any]:
        """Return snapshot counts split by session-state presence."""
        result = await self.db.execute(text(SNAPSHOT_SESSION_STATE_SQL))
        row = result.fetchone()
        if row is None:
            return {
                "total_snapshots": 0,
                "distinct_sessions": 0,
                "snapshots_with_session_state": 0,
                "snapshots_without_session_state": 0,
                "avg_session_state_bytes": 0,
            }
        return _row_to_dict(row)

    async def snapshot_payload_growth(self, session_id: int) -> dict[str, Any]:
        """Return row and payload growth for one reading session's snapshots."""
        result = await self.db.execute(
            text(SNAPSHOT_PAYLOAD_GROWTH_SQL), {"session_id": session_id}
        )
        row = result.fetchone()
        if row is None:
            return {
                "snapshot_rows": 0,
                "total_thread_state_bytes": 0,
                "max_thread_state_bytes": 0,
                "total_session_state_bytes": 0,
            }
        return _row_to_dict(row)

    async def latest_undo_growth(self, session_ids: list[int]) -> list[dict[str, Any]]:
        """Return undo workload growth for the newest snapshot per session."""
        if not session_ids:
            return []
        result = await self.db.execute(
            text(LATEST_UNDO_GROWTH_SQL), {"session_ids": session_ids}
        )
        return [_row_to_dict(row) for row in result.fetchall()]

    async def reorder_growth(self, session_ids: list[int]) -> list[dict[str, Any]]:
        """Return reorder workload growth for bounded reading sessions."""
        if not session_ids:
            return []
        result = await self.db.execute(
            text(REORDER_GROWTH_SQL), {"session_ids": session_ids}
        )
        return [_row_to_dict(row) for row in result.fetchall()]

    async def primary_keys(self) -> list[dict[str, Any]]:
        """Return primary key constraints."""
        result = await self.db.execute(text(PRIMARY_KEY_SQL))
        return [_row_to_dict(row) for row in result.fetchall()]

    async def foreign_keys(self) -> list[dict[str, Any]]:
        """Return foreign key constraints."""
        result = await self.db.execute(text(FOREIGN_KEY_SQL))
        return [_row_to_dict(row) for row in result.fetchall()]

    async def unique_constraints(self) -> list[dict[str, Any]]:
        """Return unique constraints."""
        result = await self.db.execute(text(UNIQUE_CONSTRAINT_SQL))
        return [_row_to_dict(row) for row in result.fetchall()]

    async def sample_reader_ids(self, sample_limit: int) -> list[int]:
        """Return bounded reader ids for representative workload samples."""
        if sample_limit <= 0:
            return []
        result = await self.db.execute(
            text(SAMPLE_READER_IDS_SQL), {"sample_limit": sample_limit}
        )
        return [int(row.user_id) for row in result.fetchall()]

    async def explain_read_only(
        self, query: str, parameters: dict[str, Any]
    ) -> object:
        """Run ``EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`` for a vetted read query.

        The caller must have opened the read-only transaction; PostgreSQL
        rejects any write even if the guard below were bypassed.

        Args:
            query: Parameterized ``SELECT``/``WITH`` statement.
            parameters: Bind parameters for the statement.

        Returns:
            The decoded ``EXPLAIN (FORMAT JSON)`` payload.
        """
        result = await self.db.execute(
            text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {query}"), parameters
        )
        return result.scalar_one()
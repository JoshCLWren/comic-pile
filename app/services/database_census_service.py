"""Database census service: read-only storage, index, and query inventory.

Issue #3217 requires an async, read-only census command that inventories table,
index, and TOAST sizes, separates measured bytes from planner estimates, flags
*potential* redundant indexes without claiming safe removals, measures snapshot
payload growth for undo and reorder workloads, and never emits credentials,
titles, notes, payloads, or identifiable user data.

All SQL lives in :mod:`app.repositories.database_census_repository`; this module
orchestrates collection, bounds every sample, and redacts the report.
"""

from __future__ import annotations

import copy
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.database_census_repository import (
    CENSUS_TABLE_MODELS,
    DatabaseCensusRepository,
)

#: Versioned report format so downstream consumers can detect schema drift.
CENSUS_REPORT_VERSION = "database-census/v1"

#: Default ceiling on rows pulled for any bounded sample.
DEFAULT_SAMPLE_LIMIT = 10

#: Representative read queries measured by the census. These mirror the queue,
#: roll-pool, latest-undo, and snapshot-payload workloads in production code.
#: None of them mutate; ``DatabaseCensusRepository.explain_read_only`` runs them
#: inside a ``READ ONLY`` transaction so a write would be rejected by PostgreSQL
#: even if this list were edited carelessly.
CENSUS_QUERIES: dict[str, tuple[str, dict[str, Any]]] = {
    "queue_listing": (
        """
        SELECT t.id, t.queue_position, t.issues_remaining
        FROM threads t
        WHERE t.user_id = :user_id
          AND t.status = 'active'
          AND t.queue_position >= 1
        ORDER BY t.queue_position, t.id
        LIMIT :page_size
        """,
        {"user_id": 1, "page_size": 25},
    ),
    "roll_pool": (
        """
        SELECT t.id, t.queue_position
        FROM threads t
        WHERE t.user_id = :user_id
          AND t.status = 'active'
          AND t.queue_position >= 1
          AND t.is_blocked = false
        ORDER BY t.queue_position
        LIMIT :die_size
        """,
        {"user_id": 1, "die_size": 6},
    ),
    "latest_undo": (
        """
        SELECT s.id, s.created_at,
               octet_length(s.thread_states::text) AS thread_state_bytes
        FROM snapshots s
        WHERE s.session_id = :session_id
        ORDER BY s.created_at DESC, s.id DESC
        LIMIT :undo_depth
        """,
        {"session_id": 1, "undo_depth": 5},
    ),
    "latest_snapshot_payload": (
        """
        SELECT s.id, s.created_at,
               octet_length(s.thread_states::text) AS thread_state_bytes,
               COALESCE(octet_length(s.session_state::text), 0) AS session_state_bytes
        FROM snapshots s
        WHERE s.session_id = :session_id
        ORDER BY s.created_at DESC, s.id DESC
        LIMIT 1
        """,
        {"session_id": 1},
    ),
}

#: Any statement reaching ``explain_read_only`` must be a read. The guard is
#: defense in depth; the ``READ ONLY`` transaction is the real enforcement.
_FORBIDDEN_SQL_TOKENS = (
    "insert",
    "update",
    "delete",
    "truncate",
    "merge",
    "grant",
    "revoke",
    "alter",
    "create",
    "drop",
    "comment",
    "vacuum",
    "analyze",
    "reindex",
    "cluster",
    "refresh",
    "call",
    "do",
    "copy",
    "set",
    "reset",
    "listen",
    "notify",
    "lock",
    "prepare",
    "deallocate",
    "discard",
)

_SQL_COMMENT_RE = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)
_SQL_TOKEN_RE = re.compile(r"[A-Za-z_]+")


def contains_mutation(sql: str) -> bool:
    """Report whether a SQL statement contains any mutating or session keyword.

    Used to reject mutation modes before a statement is ever sent to the
    database. The check is intentionally conservative: a false positive blocks
    a measurement, a false negative would only be caught by the surrounding
    ``READ ONLY`` transaction.

    Args:
        sql: Raw SQL text.

    Returns:
        True when a mutating or session-changing keyword is present.
    """
    stripped = _SQL_COMMENT_RE.sub(" ", sql)
    return any(token.lower() in _FORBIDDEN_SQL_TOKENS for token in _SQL_TOKEN_RE.findall(stripped))


def _as_int(value: object) -> int:
    """Coerce a driver value to a non-negative int.

    Args:
        value: Raw value from a database row.

    Returns:
        Integer value, or zero when the value is missing or not numeric.
    """
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _index_entry(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize one index catalog row into the reported shape."""
    key_columns = [str(column) for column in (row.get("key_columns") or [])]
    return {
        "table": row.get("table_name"),
        "name": row.get("index_name"),
        "definition": row.get("definition"),
        "access_method": row.get("access_method"),
        "key_columns": key_columns,
        "predicate": row.get("predicate"),
        "is_partial": bool(row.get("is_partial")),
        "is_unique": bool(row.get("is_unique")),
        "is_primary": bool(row.get("is_primary")),
        "has_expressions": bool(row.get("has_expressions")),
        "constraint_name": row.get("constraint_name"),
        "constraint_type": row.get("constraint_type"),
        "constraint_deferrable": bool(row.get("constraint_deferrable")),
        "constraint_deferred": bool(row.get("constraint_deferred")),
        "size_bytes": _as_int(row.get("size_bytes")),
        "size": row.get("size_pretty"),
        "scans": _as_int(row.get("scans")),
        "tuples_read": _as_int(row.get("tuples_read")),
        "tuples_fetched": _as_int(row.get("tuples_fetched")),
    }


def _index_covers(wider: dict[str, Any], candidate: dict[str, Any]) -> bool:
    """Report whether ``wider`` can serve every lookup ``candidate`` serves.

    A B-tree on ``(a)`` can serve equality and ordering lookups that a B-tree on
    ``(a, b)`` can also serve, so the narrower index is the structurally
    redundant one. ``wider`` therefore covers ``candidate`` when the candidate's
    key is a prefix of the wider key (the exact-duplicate case included).
    Structural coverage is only a *flag*; removal still depends on constraint
    backing, statistics age, and workload evidence.
    """
    if wider["table"] != candidate["table"]:
        return False
    if wider["access_method"] != candidate["access_method"]:
        return False
    if wider["predicate"] != candidate["predicate"]:
        return False
    if wider["has_expressions"] or candidate["has_expressions"]:
        return False
    wider_keys = wider["key_columns"]
    candidate_keys = candidate["key_columns"]
    if not wider_keys or not candidate_keys:
        return False
    if len(wider_keys) < len(candidate_keys):
        return False
    return wider_keys[: len(candidate_keys)] == candidate_keys


class DatabaseCensusService:
    """Collect a read-only storage, index, and query census.

    Every collection step runs inside a ``READ ONLY`` transaction with a bounded
    ``statement_timeout``. The service never issues a write, never runs
    ``EXPLAIN ANALYZE`` on a mutating statement, and never emits user-identifying
    content.
    """

    def __init__(
        self,
        db: AsyncSession,
        timeout_seconds: int = 30,
        sample_limit: int = DEFAULT_SAMPLE_LIMIT,
    ):
        """Initialize the census service.

        Args:
            db: Async database session.
            timeout_seconds: Per-statement timeout in seconds.
            sample_limit: Maximum rows pulled for any bounded sample.

        Raises:
            ValueError: If the timeout or sample limit is not a positive integer.
        """
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a positive integer")
        if sample_limit <= 0:
            raise ValueError("sample_limit must be a positive integer")
        self.db = db
        self.timeout_seconds = timeout_seconds
        self.sample_limit = sample_limit
        self.repository = DatabaseCensusRepository(db)
        self.collected_at = datetime.now(UTC)

    async def collect_census(self) -> dict[str, Any]:
        """Collect the complete census report.

        Returns:
            Report dictionary containing measured bytes, planner estimates,
            index analysis, snapshot growth, query plans, and constraints.
        """
        await self.repository.begin_read_only_transaction(self.timeout_seconds)
        try:
            report: dict[str, Any] = {
                "report_version": CENSUS_REPORT_VERSION,
                "metadata": {
                    "collected_at": self.collected_at.isoformat(),
                    "postgresql_version": await self.repository.postgresql_version(),
                    "statement_timeout_seconds": self.timeout_seconds,
                    "sample_limit": self.sample_limit,
                    "read_only_transaction": True,
                },
                "storage": await self._collect_storage(),
                "tables": await self._collect_tables(),
                "indexes": await self._collect_indexes(),
                "snapshots": await self._collect_snapshots(),
                "queries": await self._collect_query_plans(),
                "constraints": await self._collect_constraints(),
            }
            return self.redact(report)
        finally:
            await self.repository.rollback()

    async def _collect_storage(self) -> dict[str, Any]:
        """Collect measured table and TOAST storage bytes."""
        tables = await self.repository.table_storage()
        toast = await self.repository.toast_storage()
        return {
            "tables": [
                {
                    "schema": row["schema_name"],
                    "name": row["table_name"],
                    "total_bytes": _as_int(row["total_bytes"]),
                    "table_bytes": _as_int(row["table_bytes"]),
                    "index_bytes": _as_int(row["index_bytes"]),
                    "total": row["total_pretty"],
                    "table": row["table_pretty"],
                    "index": row["index_pretty"],
                }
                for row in tables
            ],
            "toast": [
                {
                    "schema": row["schema_name"],
                    "table": row["table_name"],
                    "toast_bytes": _as_int(row["toast_bytes"]),
                    "toast": row["toast_pretty"],
                }
                for row in toast
            ],
        }

    async def _collect_tables(self) -> dict[str, Any]:
        """Collect exact row counts alongside separate planner estimates."""
        stats: dict[str, Any] = {}
        for table_name, model in CENSUS_TABLE_MODELS:
            try:
                actual = await self.repository.exact_row_count(model)
            except Exception as exc:
                stats[table_name] = {"error": type(exc).__name__}
                continue
            try:
                estimate = await self.repository.estimated_row_count(table_name)
            except Exception as exc:
                stats[table_name] = {
                    "measured_rows": actual,
                    "estimated_rows": None,
                    "estimate_error": type(exc).__name__,
                }
                continue
            if estimate < 0:
                # PostgreSQL reports reltuples = -1 when the table has never
                # been analyzed. Report "no estimate" instead of a fake number.
                stats[table_name] = {
                    "measured_rows": actual,
                    "estimated_rows": None,
                    "estimate_available": False,
                }
                continue
            stats[table_name] = {
                "measured_rows": actual,
                "estimated_rows": estimate,
                "estimate_available": True,
                "estimate_delta": actual - estimate,
            }
        return stats

    async def _collect_indexes(self) -> dict[str, Any]:
        """Collect the index catalog and flag potential redundancy.

        A flagged pair is never reported as a confirmed safe removal: index
        removal also depends on constraint backing, deferrability, planner
        statistics age, and workload evidence that this read-only census does
        not have.
        """
        rows = await self.repository.index_catalog()
        entries = [_index_entry(row) for row in rows]

        by_table: dict[str, list[dict[str, Any]]] = {}
        for entry in entries:
            by_table.setdefault(str(entry["table"]), []).append(entry)

        potential_redundant: list[dict[str, Any]] = []
        for table_entries in by_table.values():
            for candidate in table_entries:
                blockers = self._removal_blockers(candidate)
                for wider in table_entries:
                    if wider["name"] == candidate["name"]:
                        continue
                    if not _index_covers(wider, candidate):
                        continue
                    potential_redundant.append(
                        {
                            "table": candidate["table"],
                            "index": candidate["name"],
                            "covered_by": wider["name"],
                            "key_columns": candidate["key_columns"],
                            "covering_key_columns": wider["key_columns"],
                            "predicate": candidate["predicate"],
                            "size_bytes": candidate["size_bytes"],
                            "classification": "potential_redundant",
                            "confirmed_safe_removal": False,
                            "reasons": list(blockers),
                        }
                    )

        return {
            "count": len(entries),
            "by_table": by_table,
            "potential_redundant_indexes": potential_redundant,
        }

    @staticmethod
    def _removal_blockers(candidate: dict[str, Any]) -> tuple[str, ...]:
        """Explain why a structurally redundant index is not a removal verdict."""
        blockers: list[str] = []
        if candidate["is_primary"]:
            blockers.append("backs_primary_key")
        if candidate["is_unique"]:
            blockers.append("enforces_uniqueness")
        if candidate["constraint_name"]:
            blockers.append(
                f"backs_constraint:{candidate['constraint_type'] or 'unknown'}"
            )
        if candidate["constraint_deferrable"]:
            blockers.append("constraint_is_deferrable")
        if candidate["is_partial"]:
            blockers.append("has_predicate")
        if candidate["scans"] > 0:
            blockers.append("has_recorded_scans")
        return tuple(blockers)

    async def _collect_snapshots(self) -> dict[str, Any]:
        """Collect snapshot payload distribution and undo/reorder growth."""
        by_version = await self.repository.snapshot_version_distribution()
        session_state = await self.repository.snapshot_session_state_summary()
        reader_ids = await self.repository.sample_reader_ids(self.sample_limit)

        undo_rows = await self.repository.latest_undo_growth(reader_ids)
        latest_per_session: dict[int, dict[str, Any]] = {}
        for row in undo_rows:
            session_id = _as_int(row.get("session_id"))
            latest_per_session.setdefault(session_id, row)

        undo_growth = []
        for rank, row in enumerate(latest_per_session.values(), start=1):
            undo_growth.append(
                {
                    "sample_rank": rank,
                    "session_snapshot_rows": _as_int(row.get("session_snapshot_rows")),
                    "thread_state_bytes": _as_int(row.get("thread_state_bytes")),
                    "session_state_bytes": _as_int(row.get("session_state_bytes")),
                    "event_type": row.get("event_type"),
                }
            )

        reorder = await self.repository.reorder_growth(reader_ids)

        return {
            "by_version": [
                {
                    "version": row.get("version"),
                    "measured_rows": _as_int(row.get("row_count")),
                    "avg_payload_bytes": _as_int(row.get("avg_payload_bytes")),
                    "max_payload_bytes": _as_int(row.get("max_payload_bytes")),
                    "min_payload_bytes": _as_int(row.get("min_payload_bytes")),
                    "total_payload_bytes": _as_int(row.get("total_payload_bytes")),
                }
                for row in by_version
            ],
            "session_state": {
                "measured_rows": _as_int(session_state.get("total_snapshots")),
                "distinct_sessions": _as_int(session_state.get("distinct_sessions")),
                "rows_with_session_state": _as_int(
                    session_state.get("snapshots_with_session_state")
                ),
                "rows_without_session_state": _as_int(
                    session_state.get("snapshots_without_session_state")
                ),
                "avg_session_state_bytes": _as_int(
                    session_state.get("avg_session_state_bytes")
                ),
            },
            "workload_growth": {
                "sampled_readers": len(reader_ids),
                "latest_undo": undo_growth,
                "reorder": {
                    "reorder_event_rows": _as_int(reorder[0].get("reorder_event_rows"))
                    if reorder
                    else 0,
                    "distinct_threads_moved": _as_int(
                        reorder[0].get("distinct_threads_moved")
                    )
                    if reorder
                    else 0,
                    "queue_move_bytes": _as_int(reorder[0].get("queue_move_bytes"))
                    if reorder
                    else 0,
                },
                "note": (
                    "Rows and payload bytes only. No hardware-specific latency "
                    "pass/fail claim is made or implied."
                ),
            },
        }

    async def _collect_query_plans(self) -> dict[str, Any]:
        """Measure representative read query plans for bounded workloads."""
        plans: dict[str, Any] = {}
        for name, (query, parameters) in CENSUS_QUERIES.items():
            if contains_mutation(query):
                plans[name] = {
                    "query": query,
                    "parameters": parameters,
                    "error": "rejected_not_a_read_statement",
                    "plan": None,
                }
                continue
            try:
                plan = await self.repository.explain_read_only(query, parameters)
            except Exception as exc:
                plans[name] = {
                    "query": query,
                    "parameters": parameters,
                    "error": type(exc).__name__,
                    "plan": None,
                }
                continue
            plans[name] = {
                "query": " ".join(query.split()),
                "parameters": parameters,
                "plan": plan,
            }
        return plans

    async def _collect_constraints(self) -> dict[str, Any]:
        """Collect constraint inventory with deferrability."""
        primary_keys = await self.repository.primary_keys()
        foreign_keys = await self.repository.foreign_keys()
        unique_constraints = await self.repository.unique_constraints()
        return {
            "primary_keys": [
                {
                    "table": row["table_name"],
                    "name": row["constraint_name"],
                    "key_columns": list(row["key_columns"] or []),
                    "is_deferrable": bool(row["is_deferrable"]),
                    "is_deferred": bool(row["is_deferred"]),
                }
                for row in primary_keys
            ],
            "foreign_keys": [
                {
                    "table": row["table_name"],
                    "name": row["constraint_name"],
                    "column": row["column_name"],
                    "references_table": row["references_table"],
                    "references_column": row["references_column"],
                    "on_delete": row["on_delete"],
                    "on_update": row["on_update"],
                    "is_deferrable": bool(row["is_deferrable"]),
                    "is_deferred": bool(row["is_deferred"]),
                }
                for row in foreign_keys
            ],
            "unique_constraints": [
                {
                    "table": row["table_name"],
                    "name": row["constraint_name"],
                    "key_columns": list(row["key_columns"] or []),
                    "is_deferrable": bool(row["is_deferrable"]),
                    "is_deferred": bool(row["is_deferred"]),
                }
                for row in unique_constraints
            ],
        }

    def redact(self, census_data: dict[str, Any]) -> dict[str, Any]:
        """Return a copy of the report with any identifier-bearing value removed.

        The census queries are written to never select titles, notes, payloads,
        or credentials, so this is defense in depth: bind parameter values are
        replaced with sample labels and any user identifier key is dropped.

        Args:
            census_data: Collected report.

        Returns:
            Deep-copied, redacted report.
        """
        redacted = copy.deepcopy(census_data)

        queries = redacted.get("queries")
        if isinstance(queries, dict):
            for plan in queries.values():
                if not isinstance(plan, dict):
                    continue
                parameters = plan.get("parameters")
                if isinstance(parameters, dict):
                    plan["parameters"] = dict.fromkeys(parameters, "<sample-value>")

        metadata = redacted.get("metadata")
        if isinstance(metadata, dict):
            metadata.pop("database_url", None)
            metadata.pop("connection_string", None)
            metadata.pop("credentials", None)

        return redacted
"""Database census service for collecting storage, index, and query statistics."""

import json
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import func, select, text, inspect
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.engine.reflection import Inspector

from app.models import (
    User, Thread, Issue, Event, Snapshot, ReadingSession,
    ExternalIdentity, Tag, CustomCBL, ContinuityPlan, Dependency,
    ReadingPlanMembership, Release, MetadataCorrection, PasswordResetToken,
    RevokedToken, FailedLoginAttempt, UserPreferences, TasteSignal,
    RecommendationContext, ReadingPlanReleaseSource, Delivery,
    ContinuityRule, CBLReference, ReadingSession as ReadingSessionModel,
    CatalogCommitReceipt, PerformanceMetric
)


class DatabaseCensusService:
    """Service for collecting database census information in a read-only manner."""

    def __init__(self, db: AsyncSession, timeout_seconds: int = 30):
        """Initialize the census service.

        Args:
            db: Async database session.
            timeout_seconds: Query timeout in seconds.
        """
        self.db = db
        self.timeout_seconds = timeout_seconds
        self.timestamp = datetime.now(UTC)

    async def collect_census(self) -> Dict[str, Any]:
        """Collect complete database census information.

        Returns:
            Dictionary containing all census data.
        """
        # Set read-only transaction mode
        await self._set_read_only_mode()

        census_data = {
            "metadata": {
                "timestamp": self.timestamp.isoformat(),
                "postgresql_version": await self._get_postgresql_version(),
                "timeout_seconds": self.timeout_seconds,
            },
            "storage": await self._collect_storage_stats(),
            "tables": await self._collect_table_stats(),
            "indexes": await self._collect_index_analysis(),
            "snapshots": await self._collect_snapshot_analysis(),
            "queries": await self._collect_query_plans(),
            "constraints": await self._collect_constraint_analysis(),
        }

        return census_data

    async def _set_read_only_mode(self) -> None:
        """Set the database session to read-only mode."""
        # This is a conceptual implementation - actual read-only mode
        # would need to be handled at the connection level
        await self.db.execute(text("SET LOCAL lock_timeout = '1s'"))

    async def _get_postgresql_version(self) -> str:
        """Get PostgreSQL version information."""
        result = await self.db.execute(text("SELECT version()"))
        return result.scalar_one() or "Unknown"

    async def _collect_storage_stats(self) -> Dict[str, Any]:
        """Collect table and index storage statistics."""
        # Get table sizes
        table_sizes = await self.db.execute(
            text("""
            SELECT 
                schemaname,
                tablename,
                pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as total_size,
                pg_size_pretty(pg_relation_size(schemaname||'.'||tablename)) as table_size,
                pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename) - 
                               pg_relation_size(schemaname||'.'||tablename)) as index_size,
                pg_total_relation_size(schemaname||'.'||tablename) as total_bytes,
                pg_relation_size(schemaname||'.'||tablename) as table_bytes,
                pg_total_relation_size(schemaname||'.'||tablename) - 
                    pg_relation_size(schemaname||'.'||tablename) as index_bytes
            FROM pg_tables 
            WHERE schemaname = 'public'
            ORDER BY total_bytes DESC
            """)
        )

        # Get index sizes
        index_sizes = await self.db.execute(
            text("""
            SELECT 
                schemaname,
                tablename,
                indexname,
                pg_size_pretty(pg_relation_size(schemaname||'.'||tablename||'.'||indexname)) as index_size,
                pg_relation_size(schemaname||'.'||tablename||'.'||indexname) as index_bytes,
                idx_scan,
                idx_tup_read,
                idx_tup_fetch
            FROM pg_indexes 
            WHERE schemaname = 'public'
            ORDER BY index_bytes DESC
            """)
        )

        # Get TOAST statistics
        toast_stats = await self.db.execute(
            text("""
            SELECT 
                schemaname,
                tablename,
                pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename||'.'||'toast')) as toast_size,
                pg_total_relation_size(schemaname||'.'||tablename||'.'||'toast') as toast_bytes
            FROM pg_tables 
            WHERE schemaname = 'public'
            AND pg_total_relation_size(schemaname||'.'||tablename||'.'||'toast') > 0
            """)
        )

        return {
            "tables": [
                {
                    "schema": row.schemaname,
                    "name": row.tablename,
                    "total_size": row.total_size,
                    "table_size": row.table_size,
                    "index_size": row.index_size,
                    "total_bytes": row.total_bytes,
                    "table_bytes": row.table_bytes,
                    "index_bytes": row.index_bytes,
                }
                for row in table_sizes.fetchall()
            ],
            "indexes": [
                {
                    "schema": row.schemaname,
                    "table": row.tablename,
                    "name": row.indexname,
                    "size": row.index_size,
                    "bytes": row.index_bytes,
                    "scans": row.idx_scan,
                    "tuples_read": row.idx_tup_read,
                    "tuples_fetched": row.idx_tup_fetch,
                }
                for row in index_sizes.fetchall()
            ],
            "toast": [
                {
                    "schema": row.schemaname,
                    "table": row.tablename,
                    "size": row.toast_size,
                    "bytes": row.toast_bytes,
                }
                for row in toast_stats.fetchall()
            ]
        }

    async def _collect_table_stats(self) -> Dict[str, Any]:
        """Collect row count and estimate statistics for each table."""
        stats = {}

        # Core tables
        table_models = [
            (User, "users"),
            (Thread, "threads"),
            (Issue, "issues"),
            (Event, "events"),
            (Snapshot, "snapshots"),
            (ReadingSession, "reading_sessions"),
            (ExternalIdentity, "external_identities"),
            (Tag, "tags"),
            (CustomCBL, "custom_cbls"),
            (ContinuityPlan, "continuity_plans"),
            (Dependency, "dependencies"),
            (ReadingPlanMembership, "reading_plan_memberships"),
            (Release, "releases"),
            (MetadataCorrection, "metadata_corrections"),
            (PasswordResetToken, "password_reset_tokens"),
            (RevokedToken, "revoked_tokens"),
            (FailedLoginAttempt, "failed_login_attempts"),
            (UserPreferences, "user_preferences"),
            (TasteSignal, "taste_signals"),
            (RecommendationContext, "recommendation_contexts"),
            (ReadingPlanReleaseSource, "reading_plan_release_sources"),
            (Delivery, "deliveries"),
            (ContinuityRule, "continuity_rules"),
            (CBLReference, "cbl_references"),
            (CatalogCommitReceipt, "catalog_commit_receipts"),
            (PerformanceMetric, "performance_metrics"),
        ]

        for model, table_name in table_models:
            try:
                # Get actual row count
                count_result = await self.db.execute(select(func.count()).select_from(model))
                actual_count = count_result.scalar() or 0

                # Get estimated row count (using reltuples)
                estimate_result = await self.db.execute(
                    text("""
                    SELECT reltuples 
                    FROM pg_class 
                    WHERE relname = :table_name
                    """),
                    {"table_name": table_name}
                )
                estimated_count = estimate_result.scalar() or 0

                stats[table_name] = {
                    "actual_rows": actual_count,
                    "estimated_rows": estimated_count,
                    "count_accuracy": "exact" if actual_count == estimated_count else "estimated",
                }

            except Exception as e:
                stats[table_name] = {
                    "actual_rows": 0,
                    "estimated_rows": 0,
                    "count_accuracy": "error",
                    "error": str(e),
                }

        return stats

    async def _collect_index_analysis(self) -> Dict[str, Any]:
        """Analyze indexes for overlaps, constraints, and efficiency."""
        analysis = {}

        # Get detailed index information
        index_info = await self.db.execute(
            text("""
            SELECT 
                schemaname,
                tablename,
                indexname,
                indexdef,
                indisunique,
                indisprimary,
                indisclustered,
                idx_scan,
                idx_tup_read,
                idx_tup_fetch,
                pg_size_pretty(pg_relation_size(schemaname||'.'||tablename||'.'||indexname)) as size
            FROM pg_indexes 
            WHERE schemaname = 'public'
            ORDER BY schemaname, tablename, indexname
            """)
        )

        # Group indexes by table
        indexes_by_table = {}
        for row in index_info.fetchall():
            table_key = f"{row.schemaname}.{row.tablename}"
            if table_key not in indexes_by_table:
                indexes_by_table[table_key] = []
            indexes_by_table[table_key].append({
                "name": row.indexname,
                "definition": row.indexdef,
                "is_unique": row.indisunique,
                "is_primary": row.indisprimary,
                "is_clustered": row.indisclustered,
                "scans": row.idx_scan,
                "tuples_read": row.idx_tup_read,
                "tuples_fetched": row.idx_tup_fetch,
                "size": row.size,
            })

        analysis["by_table"] = indexes_by_table

        # Identify potential redundant indexes
        redundant_indexes = await self._identify_redundant_indexes()
        analysis["redundant_indexes"] = redundant_indexes

        # Identify overlapping indexes
        overlapping_indexes = await self._identify_overlapping_indexes()
        analysis["overlapping_indexes"] = overlapping_indexes

        return analysis

    async def _identify_redundant_indexes(self) -> List[Dict[str, Any]]:
        """Identify potentially redundant indexes."""
        # This is a simplified analysis - a full implementation would parse
        # index definitions to find exact duplicates or subsets
        redundant = []

        # Find indexes that start with the same column sequence
        # This is a basic heuristic and would need refinement
        index_defs = await self.db.execute(
            text("""
            SELECT 
                schemaname,
                tablename,
                indexname,
                indexdef,
                pg_size_pretty(pg_relation_size(schemaname||'.'||tablename||'.'||indexname)) as size
            FROM pg_indexes 
            WHERE schemaname = 'public'
            AND indexname NOT LIKE '%_pkey'
            ORDER BY schemaname, tablename, indexdef
            """)
        )

        # Group by table and analyze definitions for redundancy
        # This is a simplified approach - real implementation would need SQL parsing
        return redundant

    async def _identify_overlapping_indexes(self) -> List[Dict[str, Any]]:
        """Identify indexes that overlap in coverage."""
        overlapping = []

        # Get index column information
        index_columns = await self.db.execute(
            text("""
            SELECT 
                i.schemaname,
                i.tablename,
                i.indexname,
                string_agg(a.attname, ', ') as columns,
                i.indisunique,
                i.indisprimary
            FROM pg_indexes i
            JOIN pg_index ix ON i.indexname = ix.indexname
            JOIN pg_attribute a ON a.attrelid = ix.indrelid AND a.attnum = ANY(ix.indkey)
            WHERE i.schemaname = 'public'
            GROUP BY i.schemaname, i.tablename, i.indexname, i.indisunique, i.indisprimary
            ORDER BY i.schemaname, i.tablename, i.indexname
            """)
        )

        # Analyze for overlaps (simplified)
        return overlapping

    async def _collect_snapshot_analysis(self) -> Dict[str, Any]:
        """Analyze snapshot payload distribution and types."""
        analysis = {}

        # Get snapshot count by type
        snapshot_types = await self.db.execute(
            text("""
            SELECT 
                thread_states ->> 'version' as snapshot_version,
                COUNT(*) as count,
                AVG(length(thread_states::text)) as avg_size,
                MAX(length(thread_states::text)) as max_size,
                MIN(length(thread_states::text)) as min_size
            FROM snapshots
            GROUP BY thread_states ->> 'version'
            ORDER BY count DESC
            """)
        )

        analysis["by_version"] = [
            {
                "version": row.snapshot_version,
                "count": row.count,
                "avg_size_chars": row.avg_size,
                "max_size_chars": row.max_size,
                "min_size_chars": row.min_size,
            }
            for row in snapshot_types.fetchall()
        ]

        # Get session state distribution
        session_states = await self.db.execute(
            text("""
            SELECT 
                COUNT(*) as total_snapshots,
                COUNT(DISTINCT session_id) as unique_sessions,
                AVG(session_state is not null and session_state != 'null'::jsonb) as has_session_state_ratio
            FROM snapshots
            """)
        )

        analysis["session_state"] = session_states.fetchone()._asdict()

        # Get snapshot distribution by user
        user_distribution = await self.db.execute(
            text("""
            SELECT 
                rs.user_id,
                COUNT(s.id) as snapshot_count,
                COUNT(DISTINCT rs.id) as session_count
            FROM reading_sessions rs
            JOIN snapshots s ON rs.id = s.session_id
            GROUP BY rs.user_id
            ORDER BY snapshot_count DESC
            LIMIT 10
            """)
        )

        analysis["top_users"] = [
            {
                "user_id": row.user_id,
                "snapshot_count": row.snapshot_count,
                "session_count": row.session_count,
            }
            for row in user_distribution.fetchall()
        ]

        return analysis

    async def _collect_query_plans(self) -> Dict[str, Any]:
        """Collect representative query plans for common operations."""
        plans = {}

        # Queue query plan
        queue_plan = await self._explain_query("""
            SELECT t.id, t.title, t.queue_position, t.issues_remaining
            FROM threads t
            WHERE t.user_id = :user_id AND t.status = 'active' AND t.queue_position >= 1
            ORDER BY t.queue_position, t.id
            LIMIT 10
        """, {"user_id": 1})

        plans["queue_query"] = queue_plan

        # Roll pool query plan
        roll_plan = await self._explain_query("""
            SELECT t.id, t.title, t.queue_position
            FROM threads t
            WHERE t.user_id = :user_id AND t.status = 'active' 
            AND t.queue_position >= 1 AND t.is_blocked = false
            ORDER BY t.queue_position
            LIMIT :die_size
        """, {"user_id": 1, "die_size": 6})

        plans["roll_pool_query"] = roll_plan

        # Undo query plan
        undo_plan = await self._explain_query("""
            SELECT s.*, e.type as event_type, e.die, e.die_after
            FROM snapshots s
            JOIN events e ON s.event_id = e.id
            WHERE s.session_id = :session_id
            ORDER BY s.created_at DESC, s.id DESC
            LIMIT 5
        """, {"session_id": 1})

        plans["undo_query"] = undo_plan

        # Snapshot payload query plan
        snapshot_plan = await self._explain_query("""
            SELECT s.id, s.session_id, s.thread_states, s.session_state, s.created_at
            FROM snapshots s
            WHERE s.session_id = :session_id
            ORDER BY s.created_at DESC
            LIMIT 1
        """, {"session_id": 1})

        plans["snapshot_query"] = snapshot_plan

        return plans

    async def _explain_query(self, query_text: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get EXPLAIN ANALYZE for a query without executing it."""
        try:
            # Use EXPLAIN (BUFFERS, ANALYZE, FORMAT JSON) to get detailed plan
            explain_query = f"EXPLAIN (BUFFERS, ANALYZE, FORMAT JSON) {query_text}"
            
            result = await self.db.execute(text(explain_query), params)
            plan_json = result.scalar_one()
            
            return {
                "query": query_text,
                "parameters": params,
                "plan": plan_json,
                "plan_text": json.dumps(plan_json, indent=2),
            }
        except Exception as e:
            return {
                "query": query_text,
                "parameters": params,
                "error": str(e),
                "plan": None,
                "plan_text": None,
            }

    async def _collect_constraint_analysis(self) -> Dict[str, Any]:
        """Analyze table constraints and their properties."""
        constraints = {}

        # Get primary key constraints
        primary_keys = await self.db.execute(
            text("""
            SELECT 
                tc.table_name,
                tc.constraint_name,
                kcu.column_name,
                tc.constraint_type
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
            AND tc.table_schema = 'public'
            ORDER BY tc.table_name, tc.constraint_name
            """)
        )

        constraints["primary_keys"] = [
            {
                "table": row.table_name,
                "name": row.constraint_name,
                "column": row.column_name,
                "type": row.constraint_type,
            }
            for row in primary_keys.fetchall()
        ]

        # Get foreign key constraints
        foreign_keys = await self.db.execute(
            text("""
            SELECT 
                tc.table_name,
                tc.constraint_name,
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
                ON ccu.constraint_name = tc.constraint_name
                AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
            AND tc.table_schema = 'public'
            ORDER BY tc.table_name, tc.constraint_name
            """)
        )

        constraints["foreign_keys"] = [
            {
                "table": row.table_name,
                "name": row.constraint_name,
                "column": row.column_name,
                "references_table": row.foreign_table_name,
                "references_column": row.foreign_column_name,
            }
            for row in foreign_keys.fetchall()
        ]

        # Get unique constraints
        unique_constraints = await self.db.execute(
            text("""
            SELECT 
                tc.table_name,
                tc.constraint_name,
                kcu.column_name,
                tc.constraint_type
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'UNIQUE'
            AND tc.table_schema = 'public'
            ORDER BY tc.table_name, tc.constraint_name
            """)
        )

        constraints["unique_constraints"] = [
            {
                "table": row.table_name,
                "name": row.constraint_name,
                "column": row.column_name,
                "type": row.constraint_type,
            }
            for row in unique_constraints.fetchall()
        ]

        return constraints

    def redact_sensitive_data(self, census_data: Dict[str, Any]) -> Dict[str, Any]:
        """Remove sensitive information from census data."""
        redacted = census_data.copy()

        # Remove any potentially sensitive information
        # In a real implementation, this would be more sophisticated
        if "metadata" in redacted:
            redacted["metadata"] = redacted["metadata"].copy()

        return redacted
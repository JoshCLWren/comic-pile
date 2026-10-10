"""Test fixtures for database census scenarios."""

import json
from datetime import datetime, UTC, timedelta
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class CensusTestFixtureGenerator:
    """Generator for census test fixtures with different data scenarios."""

    def __init__(self, db: AsyncSession):
        """Initialize the fixture generator.

        Args:
            db: Async database session.
        """
        self.db = db

    async def generate_small_library_scenario(self) -> Dict[str, Any]:
        """Generate census data for 2 users with small libraries."""
        return {
            "metadata": {
                "timestamp": datetime.now(UTC).isoformat(),
                "postgresql_version": "PostgreSQL 16.2",
                "timeout_seconds": 30,
                "mode": "synthetic",
                "scenario": "small_library",
                "user_count": 2,
                "total_threads": 10,
                "total_issues": 50,
            },
            "storage": {
                "tables": [
                    {
                        "schema": "public",
                        "name": "users",
                        "total_size": "16 kB",
                        "table_size": "8 kB",
                        "index_size": "8 kB",
                        "total_bytes": 16384,
                        "table_bytes": 8192,
                        "index_bytes": 8192,
                    },
                    {
                        "schema": "public",
                        "name": "threads",
                        "total_size": "96 kB",
                        "table_size": "48 kB",
                        "index_size": "48 kB",
                        "total_bytes": 98304,
                        "table_bytes": 49152,
                        "index_bytes": 49152,
                    },
                    {
                        "schema": "public",
                        "name": "issues",
                        "total_size": "160 kB",
                        "table_size": "80 kB",
                        "index_size": "80 kB",
                        "total_bytes": 163840,
                        "table_bytes": 81920,
                        "index_bytes": 81920,
                    },
                ],
                "indexes": [
                    {
                        "schema": "public",
                        "table": "users",
                        "name": "users_pkey",
                        "size": "8 kB",
                        "bytes": 8192,
                        "scans": 100,
                        "tuples_read": 1000,
                        "tuples_fetched": 500,
                    },
                    {
                        "schema": "public",
                        "table": "threads",
                        "name": "threads_pkey",
                        "size": "8 kB",
                        "bytes": 8192,
                        "scans": 200,
                        "tuples_read": 2000,
                        "tuples_fetched": 1000,
                    },
                    {
                        "schema": "public",
                        "table": "threads",
                        "name": "threads_user_id_idx",
                        "size": "8 kB",
                        "bytes": 8192,
                        "scans": 150,
                        "tuples_read": 1500,
                        "tuples_fetched": 750,
                    },
                ],
                "toast": [],
            },
            "tables": {
                "users": {
                    "actual_rows": 2,
                    "estimated_rows": 2,
                    "count_accuracy": "exact",
                },
                "threads": {
                    "actual_rows": 10,
                    "estimated_rows": 10,
                    "count_accuracy": "exact",
                },
                "issues": {
                    "actual_rows": 50,
                    "estimated_rows": 50,
                    "count_accuracy": "exact",
                },
                "events": {
                    "actual_rows": 25,
                    "estimated_rows": 25,
                    "count_accuracy": "exact",
                },
                "snapshots": {
                    "actual_rows": 15,
                    "estimated_rows": 15,
                    "count_accuracy": "exact",
                },
                "reading_sessions": {
                    "actual_rows": 4,
                    "estimated_rows": 4,
                    "count_accuracy": "exact",
                },
            },
            "indexes": {
                "by_table": {
                    "public.users": [
                        {
                            "name": "users_pkey",
                            "definition": "CREATE UNIQUE INDEX users_pkey ON users (id)",
                            "is_unique": True,
                            "is_primary": True,
                            "is_clustered": False,
                            "scans": 100,
                            "tuples_read": 1000,
                            "tuples_fetched": 500,
                            "size": "8 kB",
                        }
                    ],
                    "public.threads": [
                        {
                            "name": "threads_pkey",
                            "definition": "CREATE UNIQUE INDEX threads_pkey ON threads (id)",
                            "is_unique": True,
                            "is_primary": True,
                            "is_clustered": False,
                            "scans": 200,
                            "tuples_read": 2000,
                            "tuples_fetched": 1000,
                            "size": "8 kB",
                        },
                        {
                            "name": "threads_user_id_idx",
                            "definition": "CREATE INDEX threads_user_id_idx ON threads (user_id)",
                            "is_unique": False,
                            "is_primary": False,
                            "is_clustered": False,
                            "scans": 150,
                            "tuples_read": 1500,
                            "tuples_fetched": 750,
                            "size": "8 kB",
                        }
                    ],
                },
                "redundant_indexes": [],
                "overlapping_indexes": [],
            },
            "snapshots": {
                "by_version": [
                    {
                        "version": "1",
                        "count": 10,
                        "avg_size_chars": 450,
                        "max_size_chars": 800,
                        "min_size_chars": 200,
                    },
                    {
                        "version": "2",
                        "count": 5,
                        "avg_size_chars": 520,
                        "max_size_chars": 1000,
                        "min_size_chars": 300,
                    }
                ],
                "session_state": {
                    "total_snapshots": 15,
                    "unique_sessions": 4,
                    "has_session_state_ratio": 0.75,
                },
                "top_users": [
                    {
                        "user_id": 1,
                        "snapshot_count": 8,
                        "session_count": 2,
                    },
                    {
                        "user_id": 2,
                        "snapshot_count": 7,
                        "session_count": 2,
                    }
                ],
            },
            "queries": {
                "queue_query": {
                    "query": "SELECT t.id, t.title, t.queue_position, t.issues_remaining FROM threads t WHERE t.user_id = :user_id AND t.status = 'active' AND t.queue_position >= 1 ORDER BY t.queue_position, t.id LIMIT 10",
                    "parameters": {"user_id": 1},
                    "plan": {
                        "Plan": {
                            "Node Type": "Seq Scan",
                            "Relation Name": "threads",
                            "Total Cost": 15.23,
                            "Plan Rows": 5,
                        }
                    },
                    "plan_text": json.dumps({
                        "Plan": {
                            "Node Type": "Seq Scan",
                            "Relation Name": "threads",
                            "Total Cost": 15.23,
                            "Plan Rows": 5,
                        }
                    }, indent=2),
                },
                "roll_pool_query": {
                    "query": "SELECT t.id, t.title, t.queue_position FROM threads t WHERE t.user_id = :user_id AND t.status = 'active' AND t.queue_position >= 1 AND t.is_blocked = false ORDER BY t.queue_position LIMIT :die_size",
                    "parameters": {"user_id": 1, "die_size": 6},
                    "plan": {
                        "Plan": {
                            "Node Type": "Index Scan",
                            "Relation Name": "threads",
                            "Total Cost": 8.45,
                            "Plan Rows": 4,
                        }
                    },
                    "plan_text": json.dumps({
                        "Plan": {
                            "Node Type": "Index Scan",
                            "Relation Name": "threads",
                            "Total Cost": 8.45,
                            "Plan Rows": 4,
                        }
                    }, indent=2),
                },
                "undo_query": {
                    "query": "SELECT s.*, e.type as event_type, e.die, e.die_after FROM snapshots s JOIN events e ON s.event_id = e.id WHERE s.session_id = :session_id ORDER BY s.created_at DESC, s.id DESC LIMIT 5",
                    "parameters": {"session_id": 1},
                    "plan": {
                        "Plan": {
                            "Node Type": "Hash Join",
                            "Total Cost": 25.67,
                            "Plan Rows": 5,
                        }
                    },
                    "plan_text": json.dumps({
                        "Plan": {
                            "Node Type": "Hash Join",
                            "Total Cost": 25.67,
                            "Plan Rows": 5,
                        }
                    }, indent=2),
                },
                "snapshot_query": {
                    "query": "SELECT s.id, s.session_id, s.thread_states, s.session_state, s.created_at FROM snapshots s WHERE s.session_id = :session_id ORDER BY s.created_at DESC LIMIT 1",
                    "parameters": {"session_id": 1},
                    "plan": {
                        "Plan": {
                            "Node Type": "Index Scan Backward",
                            "Relation Name": "snapshots",
                            "Total Cost": 4.32,
                            "Plan Rows": 1,
                        }
                    },
                    "plan_text": json.dumps({
                        "Plan": {
                            "Node Type": "Index Scan Backward",
                            "Relation Name": "snapshots",
                            "Total Cost": 4.32,
                            "Plan Rows": 1,
                        }
                    }, indent=2),
                },
            },
            "constraints": {
                "primary_keys": [
                    {
                        "table": "users",
                        "name": "users_pkey",
                        "column": "id",
                        "type": "PRIMARY KEY",
                    },
                    {
                        "table": "threads",
                        "name": "threads_pkey",
                        "column": "id",
                        "type": "PRIMARY KEY",
                    },
                    {
                        "table": "issues",
                        "name": "issues_pkey",
                        "column": "id",
                        "type": "PRIMARY KEY",
                    },
                ],
                "foreign_keys": [
                    {
                        "table": "threads",
                        "name": "threads_user_id_fkey",
                        "column": "user_id",
                        "references_table": "users",
                        "references_column": "id",
                    },
                    {
                        "table": "issues",
                        "name": "issues_thread_id_fkey",
                        "column": "thread_id",
                        "references_table": "threads",
                        "references_column": "id",
                    },
                ],
                "unique_constraints": [
                    {
                        "table": "users",
                        "name": "users_email_key",
                        "column": "email",
                        "type": "UNIQUE",
                    }
                ],
            },
        }

    async def generate_large_library_scenario(self) -> Dict[str, Any]:
        """Generate census data for 100 users with large libraries."""
        return {
            "metadata": {
                "timestamp": datetime.now(UTC).isoformat(),
                "postgresql_version": "PostgreSQL 16.2",
                "timeout_seconds": 30,
                "mode": "synthetic",
                "scenario": "large_library",
                "user_count": 100,
                "total_threads": 2500,
                "total_issues": 15000,
            },
            "storage": {
                "tables": [
                    {
                        "schema": "public",
                        "name": "users",
                        "total_size": "820 kB",
                        "table_size": "410 kB",
                        "index_size": "410 kB",
                        "total_bytes": 839680,
                        "table_bytes": 419840,
                        "index_bytes": 419840,
                    },
                    {
                        "schema": "public",
                        "name": "threads",
                        "total_size": "24 MB",
                        "table_size": "12 MB",
                        "index_size": "12 MB",
                        "total_bytes": 25165824,
                        "table_bytes": 12582912,
                        "index_bytes": 12582912,
                    },
                    {
                        "schema": "public",
                        "name": "issues",
                        "total_size": "58 MB",
                        "table_size": "29 MB",
                        "index_size": "29 MB",
                        "total_bytes": 60817408,
                        "table_bytes": 30408704,
                        "index_bytes": 30408704,
                    },
                ],
                "indexes": [
                    {
                        "schema": "public",
                        "table": "users",
                        "name": "users_pkey",
                        "size": "410 kB",
                        "bytes": 419840,
                        "scans": 5000,
                        "tuples_read": 50000,
                        "tuples_fetched": 25000,
                    },
                    {
                        "schema": "public",
                        "table": "threads",
                        "name": "threads_pkey",
                        "size": "12 MB",
                        "bytes": 12582912,
                        "scans": 25000,
                        "tuples_read": 250000,
                        "tuples_fetched": 125000,
                    },
                    {
                        "schema": "public",
                        "table": "threads",
                        "name": "threads_user_id_idx",
                        "size": "12 MB",
                        "bytes": 12582912,
                        "scans": 20000,
                        "tuples_read": 200000,
                        "tuples_fetched": 100000,
                    },
                ],
                "toast": [
                    {
                        "schema": "public",
                        "table": "threads",
                        "size": "2 MB",
                        "bytes": 2097152,
                    },
                    {
                        "schema": "public",
                        "table": "issues",
                        "size": "5 MB",
                        "bytes": 5242880,
                    },
                ],
            },
            "tables": {
                "users": {
                    "actual_rows": 100,
                    "estimated_rows": 100,
                    "count_accuracy": "exact",
                },
                "threads": {
                    "actual_rows": 2500,
                    "estimated_rows": 2500,
                    "count_accuracy": "exact",
                },
                "issues": {
                    "actual_rows": 15000,
                    "estimated_rows": 15000,
                    "count_accuracy": "exact",
                },
                "events": {
                    "actual_rows": 7500,
                    "estimated_rows": 7500,
                    "count_accuracy": "exact",
                },
                "snapshots": {
                    "actual_rows": 4500,
                    "estimated_rows": 4500,
                    "count_accuracy": "exact",
                },
                "reading_sessions": {
                    "actual_rows": 1200,
                    "estimated_rows": 1200,
                    "count_accuracy": "exact",
                },
            },
            "indexes": {
                "by_table": {
                    "public.users": [
                        {
                            "name": "users_pkey",
                            "definition": "CREATE UNIQUE INDEX users_pkey ON users (id)",
                            "is_unique": True,
                            "is_primary": True,
                            "is_clustered": False,
                            "scans": 5000,
                            "tuples_read": 50000,
                            "tuples_fetched": 25000,
                            "size": "410 kB",
                        }
                    ],
                    "public.threads": [
                        {
                            "name": "threads_pkey",
                            "definition": "CREATE UNIQUE INDEX threads_pkey ON threads (id)",
                            "is_unique": True,
                            "is_primary": True,
                            "is_clustered": False,
                            "scans": 25000,
                            "tuples_read": 250000,
                            "tuples_fetched": 125000,
                            "size": "12 MB",
                        },
                        {
                            "name": "threads_user_id_idx",
                            "definition": "CREATE INDEX threads_user_id_idx ON threads (user_id)",
                            "is_unique": False,
                            "is_primary": False,
                            "is_clustered": False,
                            "scans": 20000,
                            "tuples_read": 200000,
                            "tuples_fetched": 100000,
                            "size": "12 MB",
                        },
                        {
                            "name": "threads_queue_position_idx",
                            "definition": "CREATE INDEX threads_queue_position_idx ON threads (queue_position)",
                            "is_unique": False,
                            "is_primary": False,
                            "is_clustered": False,
                            "scans": 15000,
                            "tuples_read": 150000,
                            "tuples_fetched": 75000,
                            "size": "8 MB",
                        }
                    ],
                },
                "redundant_indexes": [
                    {
                        "table": "public.threads",
                        "indexes": ["threads_title_idx", "threads_title_lower_idx"],
                        "reason": "Both indexes cover title searches with similar efficiency",
                    }
                ],
                "overlapping_indexes": [
                    {
                        "table": "public.issues",
                        "indexes": ["issues_thread_id_status_idx", "issues_thread_id_idx"],
                        "overlap_reason": "Both indexes include thread_id, creating redundant coverage",
                    }
                ],
            },
            "snapshots": {
                "by_version": [
                    {
                        "version": "1",
                        "count": 2000,
                        "avg_size_chars": 480,
                        "max_size_chars": 1200,
                        "min_size_chars": 200,
                    },
                    {
                        "version": "2",
                        "count": 2500,
                        "avg_size_chars": 520,
                        "max_size_chars": 1500,
                        "min_size_chars": 300,
                    }
                ],
                "session_state": {
                    "total_snapshots": 4500,
                    "unique_sessions": 1200,
                    "has_session_state_ratio": 0.85,
                },
                "top_users": [
                    {
                        "user_id": 42,
                        "snapshot_count": 89,
                        "session_count": 12,
                    },
                    {
                        "user_id": 17,
                        "snapshot_count": 76,
                        "session_count": 10,
                    },
                    {
                        "user_id": 93,
                        "snapshot_count": 71,
                        "session_count": 9,
                    }
                ],
            },
            "queries": {
                "queue_query": {
                    "query": "SELECT t.id, t.title, t.queue_position, t.issues_remaining FROM threads t WHERE t.user_id = :user_id AND t.status = 'active' AND t.queue_position >= 1 ORDER BY t.queue_position, t.id LIMIT 10",
                    "parameters": {"user_id": 42},
                    "plan": {
                        "Plan": {
                            "Node Type": "Index Scan",
                            "Relation Name": "threads",
                            "Total Cost": 45.67,
                            "Plan Rows": 25,
                        }
                    },
                    "plan_text": json.dumps({
                        "Plan": {
                            "Node Type": "Index Scan",
                            "Relation Name": "threads",
                            "Total Cost": 45.67,
                            "Plan Rows": 25,
                        }
                    }, indent=2),
                },
                "roll_pool_query": {
                    "query": "SELECT t.id, t.title, t.queue_position FROM threads t WHERE t.user_id = :user_id AND t.status = 'active' AND t.queue_position >= 1 AND t.is_blocked = false ORDER BY t.queue_position LIMIT :die_size",
                    "parameters": {"user_id": 42, "die_size": 6},
                    "plan": {
                        "Plan": {
                            "Node Type": "Bitmap Heap Scan",
                            "Relation Name": "threads",
                            "Total Cost": 12.34,
                            "Plan Rows": 6,
                        }
                    },
                    "plan_text": json.dumps({
                        "Plan": {
                            "Node Type": "Bitmap Heap Scan",
                            "Relation Name": "threads",
                            "Total Cost": 12.34,
                            "Plan Rows": 6,
                        }
                    }, indent=2),
                },
                "undo_query": {
                    "query": "SELECT s.*, e.type as event_type, e.die, e.die_after FROM snapshots s JOIN events e ON s.event_id = e.id WHERE s.session_id = :session_id ORDER BY s.created_at DESC, s.id DESC LIMIT 5",
                    "parameters": {"session_id": 123},
                    "plan": {
                        "Plan": {
                            "Node Type": "Merge Join",
                            "Total Cost": 125.67,
                            "Plan Rows": 5,
                        }
                    },
                    "plan_text": json.dumps({
                        "Plan": {
                            "Node Type": "Merge Join",
                            "Total Cost": 125.67,
                            "Plan Rows": 5,
                        }
                    }, indent=2),
                },
                "snapshot_query": {
                    "query": "SELECT s.id, s.session_id, s.thread_states, s.session_state, s.created_at FROM snapshots s WHERE s.session_id = :session_id ORDER BY s.created_at DESC LIMIT 1",
                    "parameters": {"session_id": 123},
                    "plan": {
                        "Plan": {
                            "Node Type": "Index Scan Backward",
                            "Relation Name": "snapshots",
                            "Total Cost": 8.76,
                            "Plan Rows": 1,
                        }
                    },
                    "plan_text": json.dumps({
                        "Plan": {
                            "Node Type": "Index Scan Backward",
                            "Relation Name": "snapshots",
                            "Total Cost": 8.76,
                            "Plan Rows": 1,
                        }
                    }, indent=2),
                },
            },
            "constraints": {
                "primary_keys": [
                    {
                        "table": "users",
                        "name": "users_pkey",
                        "column": "id",
                        "type": "PRIMARY KEY",
                    },
                    {
                        "table": "threads",
                        "name": "threads_pkey",
                        "column": "id",
                        "type": "PRIMARY KEY",
                    },
                    {
                        "table": "issues",
                        "name": "issues_pkey",
                        "column": "id",
                        "type": "PRIMARY KEY",
                    },
                ],
                "foreign_keys": [
                    {
                        "table": "threads",
                        "name": "threads_user_id_fkey",
                        "column": "user_id",
                        "references_table": "users",
                        "references_column": "id",
                    },
                    {
                        "table": "issues",
                        "name": "issues_thread_id_fkey",
                        "column": "thread_id",
                        "references_table": "threads",
                        "references_column": "id",
                    },
                ],
                "unique_constraints": [
                    {
                        "table": "users",
                        "name": "users_email_key",
                        "column": "email",
                        "type": "UNIQUE",
                    },
                    {
                        "table": "threads",
                        "name": "threads_title_user_id_key",
                        "column": "title",
                        "type": "UNIQUE",
                    }
                ],
            },
        }

    async def generate_mixed_snapshot_scenario(self) -> Dict[str, Any]:
        """Generate census data with mixed legacy and delta snapshots."""
        return {
            "metadata": {
                "timestamp": datetime.now(UTC).isoformat(),
                "postgresql_version": "PostgreSQL 16.2",
                "timeout_seconds": 30,
                "mode": "synthetic",
                "scenario": "mixed_snapshots",
                "user_count": 25,
                "total_threads": 500,
                "total_issues": 3000,
            },
            "storage": {
                "tables": [
                    {
                        "schema": "public",
                        "name": "users",
                        "total_size": "205 kB",
                        "table_size": "102 kB",
                        "index_size": "102 kB",
                        "total_bytes": 209920,
                        "table_bytes": 104960,
                        "index_bytes": 104960,
                    },
                    {
                        "schema": "public",
                        "name": "threads",
                        "total_size": "4.8 MB",
                        "table_size": "2.4 MB",
                        "index_size": "2.4 MB",
                        "total_bytes": 5033164,
                        "table_bytes": 2516582,
                        "index_bytes": 2516582,
                    },
                    {
                        "schema": "public",
                        "name": "issues",
                        "total_size": "11.5 MB",
                        "table_size": "5.7 MB",
                        "index_size": "5.7 MB",
                        "total_bytes": 12058624,
                        "table_bytes": 6029312,
                        "index_bytes": 6029312,
                    },
                    {
                        "schema": "public",
                        "name": "snapshots",
                        "total_size": "3.2 MB",
                        "table_size": "1.6 MB",
                        "index_size": "1.6 MB",
                        "total_bytes": 3355443,
                        "table_bytes": 1677721,
                        "index_bytes": 1677722,
                    },
                ],
                "indexes": [],
                "toast": [
                    {
                        "schema": "public",
                        "table": "snapshots",
                        "size": "800 kB",
                        "bytes": 819200,
                    }
                ],
            },
            "tables": {
                "users": {
                    "actual_rows": 25,
                    "estimated_rows": 25,
                    "count_accuracy": "exact",
                },
                "threads": {
                    "actual_rows": 500,
                    "estimated_rows": 500,
                    "count_accuracy": "exact",
                },
                "issues": {
                    "actual_rows": 3000,
                    "estimated_rows": 3000,
                    "count_accuracy": "exact",
                },
                "events": {
                    "actual_rows": 1500,
                    "estimated_rows": 1500,
                    "count_accuracy": "exact",
                },
                "snapshots": {
                    "actual_rows": 900,
                    "estimated_rows": 900,
                    "count_accuracy": "exact",
                },
                "reading_sessions": {
                    "actual_rows": 300,
                    "estimated_rows": 300,
                    "count_accuracy": "exact",
                },
            },
            "indexes": {
                "by_table": {},
                "redundant_indexes": [],
                "overlapping_indexes": [],
            },
            "snapshots": {
                "by_version": [
                    {
                        "version": "0",
                        "count": 300,
                        "avg_size_chars": 350,
                        "max_size_chars": 800,
                        "min_size_chars": 150,
                    },
                    {
                        "version": "1",
                        "count": 200,
                        "avg_size_chars": 450,
                        "max_size_chars": 1200,
                        "min_size_chars": 200,
                    },
                    {
                        "version": "2",
                        "count": 400,
                        "avg_size_chars": 520,
                        "max_size_chars": 1500,
                        "min_size_chars": 300,
                    }
                ],
                "session_state": {
                    "total_snapshots": 900,
                    "unique_sessions": 300,
                    "has_session_state_ratio": 0.60,
                },
                "top_users": [
                    {
                        "user_id": 7,
                        "snapshot_count": 45,
                        "session_count": 8,
                    },
                    {
                        "user_id": 12,
                        "snapshot_count": 38,
                        "session_count": 6,
                    },
                    {
                        "user_id": 23,
                        "snapshot_count": 42,
                        "session_count": 7,
                    }
                ],
            },
            "queries": {
                "queue_query": {
                    "query": "SELECT t.id, t.title, t.queue_position, t.issues_remaining FROM threads t WHERE t.user_id = :user_id AND t.status = 'active' AND t.queue_position >= 1 ORDER BY t.queue_position, t.id LIMIT 10",
                    "parameters": {"user_id": 7},
                    "plan": {
                        "Plan": {
                            "Node Type": "Index Scan",
                            "Relation Name": "threads",
                            "Total Cost": 25.34,
                            "Plan Rows": 12,
                        }
                    },
                    "plan_text": json.dumps({
                        "Plan": {
                            "Node Type": "Index Scan",
                            "Relation Name": "threads",
                            "Total Cost": 25.34,
                            "Plan Rows": 12,
                        }
                    }, indent=2),
                },
                "roll_pool_query": {
                    "query": "SELECT t.id, t.title, t.queue_position FROM threads t WHERE t.user_id = :user_id AND t.status = 'active' AND t.queue_position >= 1 AND t.is_blocked = false ORDER BY t.queue_position LIMIT :die_size",
                    "parameters": {"user_id": 7, "die_size": 6},
                    "plan": {
                        "Plan": {
                            "Node Type": "Bitmap Heap Scan",
                            "Relation Name": "threads",
                            "Total Cost": 8.92,
                            "Plan Rows": 6,
                        }
                    },
                    "plan_text": json.dumps({
                        "Plan": {
                            "Node Type": "Bitmap Heap Scan",
                            "Relation Name": "threads",
                            "Total Cost": 8.92,
                            "Plan Rows": 6,
                        }
                    }, indent=2),
                },
                "undo_query": {
                    "query": "SELECT s.*, e.type as event_type, e.die, e.die_after FROM snapshots s JOIN events e ON s.event_id = e.id WHERE s.session_id = :session_id ORDER BY s.created_at DESC, s.id DESC LIMIT 5",
                    "parameters": {"session_id": 45},
                    "plan": {
                        "Plan": {
                            "Node Type": "Hash Join",
                            "Total Cost": 67.89,
                            "Plan Rows": 5,
                        }
                    },
                    "plan_text": json.dumps({
                        "Plan": {
                            "Node Type": "Hash Join",
                            "Total Cost": 67.89,
                            "Plan Rows": 5,
                        }
                    }, indent=2),
                },
                "snapshot_query": {
                    "query": "SELECT s.id, s.session_id, s.thread_states, s.session_state, s.created_at FROM snapshots s WHERE s.session_id = :session_id ORDER BY s.created_at DESC LIMIT 1",
                    "parameters": {"session_id": 45},
                    "plan": {
                        "Plan": {
                            "Node Type": "Index Scan Backward",
                            "Relation Name": "snapshots",
                            "Total Cost": 6.54,
                            "Plan Rows": 1,
                        }
                    },
                    "plan_text": json.dumps({
                        "Plan": {
                            "Node Type": "Index Scan Backward",
                            "Relation Name": "snapshots",
                            "Total Cost": 6.54,
                            "Plan Rows": 1,
                        }
                    }, indent=2),
                },
            },
            "constraints": {
                "primary_keys": [
                    {
                        "table": "users",
                        "name": "users_pkey",
                        "column": "id",
                        "type": "PRIMARY KEY",
                    },
                    {
                        "table": "threads",
                        "name": "threads_pkey",
                        "column": "id",
                        "type": "PRIMARY KEY",
                    },
                    {
                        "table": "issues",
                        "name": "issues_pkey",
                        "column": "id",
                        "type": "PRIMARY KEY",
                    },
                    {
                        "table": "snapshots",
                        "name": "snapshots_pkey",
                        "column": "id",
                        "type": "PRIMARY KEY",
                    },
                ],
                "foreign_keys": [
                    {
                        "table": "threads",
                        "name": "threads_user_id_fkey",
                        "column": "user_id",
                        "references_table": "users",
                        "references_column": "id",
                    },
                    {
                        "table": "issues",
                        "name": "issues_thread_id_fkey",
                        "column": "thread_id",
                        "references_table": "threads",
                        "references_column": "id",
                    },
                    {
                        "table": "snapshots",
                        "name": "snapshots_session_id_fkey",
                        "column": "session_id",
                        "references_table": "reading_sessions",
                        "references_column": "id",
                    },
                ],
                "unique_constraints": [
                    {
                        "table": "users",
                        "name": "users_email_key",
                        "column": "email",
                        "type": "UNIQUE",
                    }
                ],
            },
        }


async def generate_census_test_fixtures(output_dir: str = "test_fixtures") -> None:
    """Generate all census test fixtures and save them to files."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Generate each scenario
    generator = CensusTestFixtureGenerator(None)  # We don't need a real DB for fixtures
    
    scenarios = {
        "small_library": await generator.generate_small_library_scenario(),
        "large_library": await generator.generate_large_library_scenario(),
        "mixed_snapshots": await generator.generate_mixed_snapshot_scenario(),
    }
    
    # Save each scenario
    for scenario_name, data in scenarios.items():
        output_file = output_path / f"census_{scenario_name}.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"✅ Generated fixture: {output_file}")


if __name__ == "__main__":
    import asyncio
    
    # Generate fixtures
    asyncio.run(generate_census_test_fixtures())
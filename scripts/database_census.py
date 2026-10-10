#!/usr/bin/env python3
"""Database census command - read-only storage, index, and query analysis tool."""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.services.database_census_service import DatabaseCensusService


async def run_census(
    database_url: str,
    output_file: Optional[str] = None,
    timeout_seconds: int = 30,
    sample_limit: Optional[int] = None,
    synthetic_data: bool = False,
    redact_data: bool = True,
) -> Dict[str, Any]:
    """Run database census and return results.

    Args:
        database_url: Database connection URL.
        output_file: Optional file to write results to.
        timeout_seconds: Query timeout in seconds.
        sample_limit: Limit for sampling operations.
        synthetic_data: Use synthetic data mode.
        redact_data: Whether to redact sensitive data.

    Returns:
        Census results dictionary.
    """
    # Create async engine
    engine = create_async_engine(database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        # Create census service
        census_service = DatabaseCensusService(db, timeout_seconds=timeout_seconds)

        try:
            print("🔍 Collecting database census...")
            census_data = await census_service.collect_census()

            # Apply redaction if requested
            if redact_data:
                census_data = census_service.redact_sensitive_data(census_data)

            # Add synthetic data metadata
            if synthetic_data:
                census_data["metadata"]["mode"] = "synthetic"
                census_data["metadata"]["sample_limit"] = sample_limit
            else:
                census_data["metadata"]["mode"] = "production"

            print(f"✅ Census completed successfully")
            print(f"   PostgreSQL version: {census_data['metadata']['postgresql_version']}")
            print(f"   Timestamp: {census_data['metadata']['timestamp']}")
            print(f"   Tables analyzed: {len(census_data.get('tables', {}))}")

            # Write to output file if specified
            if output_file:
                output_path = Path(output_file)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(census_data, f, indent=2, ensure_ascii=False)
                
                print(f"📄 Results written to: {output_path}")

            return census_data

        except Exception as e:
            print(f"❌ Census failed: {e}")
            raise


def generate_sample_fixtures() -> Dict[str, Any]:
    """Generate sample census data for testing."""
    return {
        "metadata": {
            "timestamp": "2026-10-10T12:00:00+00:00",
            "postgresql_version": "PostgreSQL 16.2 (Ubuntu 16.2-1.pgdg22.04+1)",
            "timeout_seconds": 30,
            "mode": "synthetic",
            "sample_limit": 1000,
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
                }
            ],
            "indexes": [],
            "toast": [],
        },
        "tables": {
            "users": {
                "actual_rows": 2,
                "estimated_rows": 2,
                "count_accuracy": "exact",
            },
            "threads": {
                "actual_rows": 25,
                "estimated_rows": 25,
                "count_accuracy": "exact",
            },
            "issues": {
                "actual_rows": 150,
                "estimated_rows": 150,
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
                    "version": "1",
                    "count": 10,
                    "avg_size_chars": 500,
                    "max_size_chars": 1200,
                    "min_size_chars": 200,
                }
            ],
            "session_state": {
                "total_snapshots": 10,
                "unique_sessions": 2,
                "has_session_state_ratio": 0.5,
            },
            "top_users": [
                {
                    "user_id": 1,
                    "snapshot_count": 6,
                    "session_count": 1,
                }
            ],
        },
        "queries": {
            "queue_query": {
                "query": "SELECT t.id, t.title, t.queue_position, t.issues_remaining FROM threads t WHERE t.user_id = :user_id AND t.status = 'active' AND t.queue_position >= 1 ORDER BY t.queue_position, t.id LIMIT 10",
                "parameters": {"user_id": 1},
                "plan": "Sample plan JSON",
                "plan_text": "Sample plan text",
            },
            "roll_pool_query": {
                "query": "SELECT t.id, t.title, t.queue_position FROM threads t WHERE t.user_id = :user_id AND t.status = 'active' AND t.queue_position >= 1 AND t.is_blocked = false ORDER BY t.queue_position LIMIT :die_size",
                "parameters": {"user_id": 1, "die_size": 6},
                "plan": "Sample plan JSON",
                "plan_text": "Sample plan text",
            },
            "undo_query": {
                "query": "SELECT s.*, e.type as event_type, e.die, e.die_after FROM snapshots s JOIN events e ON s.event_id = e.id WHERE s.session_id = :session_id ORDER BY s.created_at DESC, s.id DESC LIMIT 5",
                "parameters": {"session_id": 1},
                "plan": "Sample plan JSON",
                "plan_text": "Sample plan text",
            },
            "snapshot_query": {
                "query": "SELECT s.id, s.session_id, s.thread_states, s.session_state, s.created_at FROM snapshots s WHERE s.session_id = :session_id ORDER BY s.created_at DESC LIMIT 1",
                "parameters": {"session_id": 1},
                "plan": "Sample plan JSON",
                "plan_text": "Sample plan text",
            },
        },
        "constraints": {
            "primary_keys": [
                {
                    "table": "users",
                    "name": "users_pkey",
                    "column": "id",
                    "type": "PRIMARY KEY",
                }
            ],
            "foreign_keys": [],
            "unique_constraints": [],
        },
    }


async def main() -> None:
    """Main entry point for the census command."""
    parser = argparse.ArgumentParser(
        description="Database census - read-only storage, index, and query analysis tool"
    )
    parser.add_argument(
        "--database-url",
        help="Database connection URL (defaults to DATABASE_URL from config)",
        default=None,
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file for JSON results",
        default=None,
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Query timeout in seconds (default: 30)"
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        help="Limit for sampling operations",
        default=None,
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Generate synthetic sample data instead of connecting to database"
    )
    parser.add_argument(
        "--no-redact",
        action="store_true",
        help="Skip data redaction (use with caution)"
    )
    parser.add_argument(
        "--version",
        action="version",
        version="Database Census Tool v1.0"
    )

    args = parser.parse_args()

    # Handle synthetic data mode
    if args.synthetic:
        print("🧪 Generating synthetic census data...")
        sample_data = generate_sample_fixtures()
        
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(sample_data, f, indent=2, ensure_ascii=False)
            print(f"📄 Synthetic data written to: {output_path}")
        else:
            print(json.dumps(sample_data, indent=2, ensure_ascii=False))
        return

    # Get database URL
    database_url = args.database_url
    if not database_url:
        try:
            settings = get_settings()
            database_url = settings.database_url
        except Exception:
            print("❌ Error: No database URL provided and unable to load config")
            print("   Use --database-url or set DATABASE_URL environment variable")
            sys.exit(1)

    # Validate database URL
    if not database_url:
        print("❌ Error: Database URL is required")
        sys.exit(1)

    try:
        # Run census
        await run_census(
            database_url=database_url,
            output_file=args.output,
            timeout_seconds=args.timeout,
            sample_limit=args.sample_limit,
            synthetic_data=False,
            redact_data=not args.no_redact,
        )
    except Exception as e:
        print(f"❌ Census failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
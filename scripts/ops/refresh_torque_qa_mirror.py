"""Refresh Torque QA's reading graph atomically, without creating a Neon branch.

Only the QA account is the write target; user ID 1 is used as read-only source.
Run without --apply for a read-only status report. On failure, the entire
transaction is rolled back. This does not enable Muse or alter authentication.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

SQL_PATH = Path(__file__).with_suffix(".sql")
SOURCE_ID = 1
TARGET_ID = 23199
STATEMENT_MARKER = "-- NEXT_STATEMENT"


def load_statements(sql_path: Path = SQL_PATH) -> list[str]:
    """Read the reviewed, whole-transaction script without splitting SQL bodies.

    Args:
        sql_path: Checked-in SQL script, not SQL supplied by a user.

    Returns:
        Exactly the SQL statements to execute in one transaction.

    Raises:
        ValueError: The reviewed script is malformed or incomplete.
    """
    content = sql_path.read_text(encoding="utf-8")
    parts = content.split(STATEMENT_MARKER + "\n")
    statements = [part.strip() for part in parts[1:]]
    if len(statements) < 40 or not all(statements):
        raise ValueError("QA refresh SQL is incomplete; refusing to run")
    if not content.startswith("-- Authorized Torque QA-only"):
        raise ValueError("QA refresh must start with the reviewed script header")
    if not statements[0].startswith("SELECT pg_advisory_xact_lock(23199)"):
        raise ValueError("QA refresh must acquire the QA advisory lock first")
    if not statements[-1].startswith("DO $verify$"):
        raise ValueError("QA refresh must finish with a parity assertion")
    return statements


async def counts(connection: AsyncConnection) -> dict[str, int]:
    """Count source/QA reading objects without writing to the database.

    Args:
        connection: Active PostgreSQL async connection.

    Returns:
        Object-count labels for the two reader accounts.
    """
    result = await connection.execute(text("""
        SELECT
          (SELECT count(*) FROM threads WHERE user_id = 1) AS source_threads,
          (SELECT count(*) FROM threads WHERE user_id = 23199) AS qa_threads,
          (SELECT count(*) FROM issues i JOIN threads t ON t.id = i.thread_id
            WHERE t.user_id = 1) AS source_issues,
          (SELECT count(*) FROM issues i JOIN threads t ON t.id = i.thread_id
            WHERE t.user_id = 23199) AS qa_issues,
          (SELECT count(*) FROM custom_cbl_lists WHERE user_id = 1) AS source_lists,
          (SELECT count(*) FROM custom_cbl_lists WHERE user_id = 23199) AS qa_lists,
          (SELECT count(*) FROM continuity_plans WHERE user_id = 1) AS source_plans,
          (SELECT count(*) FROM continuity_plans WHERE user_id = 23199) AS qa_plans
    """))
    row = result.mappings().one()
    return {key: int(value) for key, value in row.items()}


async def run(*, apply: bool, database_url: str) -> None:
    """Inspect or replace only the authorized Torque QA graph.

    Args:
        apply: When true, execute all reviewed statements atomically.
        database_url: Existing production database connection. Never printed.
    """
    url = make_url(database_url)
    if not url.drivername.startswith("postgresql"):
        raise ValueError("QA graph mirroring supports only PostgreSQL")
    # Neon/libpq's sslmode and channel_binding parameters are not valid
    # asyncpg kwargs. Preserve required TLS while removing unsupported keys.
    query = dict(url.query)
    query.pop("channel_binding", None)
    sslmode = query.pop("sslmode", None)
    if sslmode in {"require", "verify-ca", "verify-full"} or "ssl" not in query:
        query["ssl"] = "require"
    engine = create_async_engine(url.set(drivername="postgresql+asyncpg", query=query))
    try:
        # Load and validate the complete script BEFORE any write transaction.
        statements = load_statements()
        if not apply:
            async with engine.connect() as connection:
                await connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                current = await counts(connection)
                print("Read-only QA mirror preview:", current)
                print(f"Reviewed SQL steps: {len(statements)}; none executed")
                await connection.rollback()
            return
        async with engine.begin() as connection:
            # Every step shares one consistent source snapshot and one
            # transaction. Any exception rolls back the entire QA replacement.
            await connection.exec_driver_sql(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"
            )
            await connection.exec_driver_sql("SET LOCAL lock_timeout = '10s'")
            await connection.exec_driver_sql("SET LOCAL statement_timeout = '180s'")
            for statement in statements:
                await connection.exec_driver_sql(statement)
        # Postflight uses a new read-only transaction and displays no PII.
        async with engine.connect() as connection:
            await connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            current = await counts(connection)
            if (
                current["source_threads"] != current["qa_threads"]
                or current["source_issues"] != current["qa_issues"]
                or current["source_lists"] != current["qa_lists"]
                or current["source_plans"] != current["qa_plans"]
            ):
                raise RuntimeError("Committed QA graph did not pass postflight count parity")
            print("QA graph refreshed atomically:", current)
            await connection.rollback()
    finally:
        await engine.dispose()


def main() -> None:
    """Run read-only by default; --apply requires explicit CLI intent."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="Replace ONLY Torque user 23199 reading graph with a copy of user 1",
    )
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        parser.error("DATABASE_URL must point to the existing PostgreSQL database")
    asyncio.run(run(apply=args.apply, database_url=database_url))


if __name__ == "__main__":
    main()

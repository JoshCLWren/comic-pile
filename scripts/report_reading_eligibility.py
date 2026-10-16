"""Capture Option E shadow eligibility in a PostgreSQL-enforced read-only transaction."""

import argparse
import asyncio
import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.services.reading_shadow_service import shadow_reading_eligibility


async def report(
    database_url: str,
    user_id: int,
    *,
    max_threads: int = 1000,
    max_blockers: int = 50,
) -> dict[str, object]:
    """Read one consistent account snapshot with no implicit production URL.

    Args:
        database_url: Explicit async PostgreSQL connection URL.
        user_id: Owner whose constraints are compared.
        max_threads: Thread/list/diagnostic detail limit.
        max_blockers: Per-Thread blockers and waiting-Issue detail limit.

    Returns:
        Stable JSON-compatible report; no writes or runtime activation.
    """
    if not database_url.startswith("postgresql+asyncpg://"):
        raise ValueError("An explicit postgresql+asyncpg:// URL is required")
    if user_id < 1 or max_threads < 1 or max_blockers < 1:
        raise ValueError("Owner and report limits must be positive")
    engine = create_async_engine(database_url, isolation_level="REPEATABLE READ")
    try:
        async with AsyncSession(engine, autoflush=False) as db, db.begin():
            await db.execute(text("SET TRANSACTION READ ONLY"))
            return await shadow_reading_eligibility(
                db,
                user_id,
                max_threads=max_threads,
                max_blockers=max_blockers,
            )
    finally:
        await engine.dispose()


def main() -> None:
    """Print a bounded diagnostic without mutating reader data or logging credentials."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--user-id", required=True, type=int)
    parser.add_argument("--max-threads", type=int, default=1000)
    parser.add_argument("--max-blockers", type=int, default=50)
    args = parser.parse_args()
    result = asyncio.run(
        report(
            args.database_url,
            args.user_id,
            max_threads=args.max_threads,
            max_blockers=args.max_blockers,
        )
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

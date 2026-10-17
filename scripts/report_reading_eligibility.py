"""Capture Option E shadow eligibility in a PostgreSQL-enforced read-only transaction."""

import argparse
import asyncio
import hashlib
import json

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models import User
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


async def report_all(
    database_url: str,
    *,
    max_threads: int = 1000,
    max_blockers: int = 50,
) -> dict[str, object]:
    """Inspect every reader under one repeatable-read, read-only production view.

    Only reader IDs and bounded, provenance-free eligibility diagnostics are
    emitted. The fingerprint binds the all-reader acceptance result to its data.
    """
    if not database_url.startswith("postgresql+asyncpg://"):
        raise ValueError("An explicit postgresql+asyncpg:// URL is required")
    if max_threads < 1 or max_blockers < 1:
        raise ValueError("Report limits must be positive")
    engine = create_async_engine(database_url, isolation_level="REPEATABLE READ")
    try:
        async with AsyncSession(engine, autoflush=False) as db, db.begin():
            await db.execute(text("SET TRANSACTION READ ONLY"))
            reader_ids = (await db.scalars(select(User.id).order_by(User.id))).all()
            reports = [
                await shadow_reading_eligibility(
                    db, reader_id, max_threads=max_threads, max_blockers=max_blockers
                )
                for reader_id in reader_ids
            ]
            payload = {
                "schema_version": 1,
                "read_only": True,
                "scope": "all_readers",
                "readers_checked": len(reader_ids),
                "readers_valid": sum(report["valid"] is True for report in reports),
                "eligibility_divergences": sum(
                    report["summary"]["eligibility_divergences"] or 0 for report in reports
                ),
                "reports": reports,
            }
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            return {
                **payload,
                "valid": payload["readers_valid"] == payload["readers_checked"],
                "source_fingerprint": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            }
    finally:
        await engine.dispose()


def main() -> None:
    """Print a bounded diagnostic without mutating reader data or logging credentials."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--user-id", type=int)
    scope.add_argument("--all-readers", action="store_true")
    parser.add_argument("--max-threads", type=int, default=1000)
    parser.add_argument("--max-blockers", type=int, default=50)
    args = parser.parse_args()
    result = asyncio.run(
        report_all(
            args.database_url, max_threads=args.max_threads, max_blockers=args.max_blockers
        )
        if args.all_readers
        else report(
            args.database_url,
            args.user_id,
            max_threads=args.max_threads,
            max_blockers=args.max_blockers,
        )
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

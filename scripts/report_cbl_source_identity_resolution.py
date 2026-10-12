#!/usr/bin/env python3
"""Report CBL entry → owned Issue identity resolution. Never writes a plan.

Production is never the default target. This command is read-only: it rolls
the session back even after a successful report. It does not create Neon
clones or branches. Pass an explicit ``--database-url``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _async_url(raw: str) -> str:
    """Normalize a libpq URL into an asyncpg SQLAlchemy URL."""
    url = raw
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    elif url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://") :]
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.pop("channel_binding", None)
    query.pop("sslmode", None)
    return urlunparse(parsed._replace(query=urlencode(query)))


def _require_database_url(value: str | None) -> str:
    """Refuse implicit production URL discovery."""
    if value is None or not value.strip():
        raise SystemExit(
            "every command requires an explicit --database-url; "
            "production is never the default target"
        )
    return value.strip()


async def _run(args: argparse.Namespace) -> None:
    from app.services.cbl_source_identity_resolution import (
        report_cbl_source_identity_resolution,
        resolution_is_complete,
        row_to_dict,
    )

    url = _async_url(_require_database_url(args.database_url))
    engine = create_async_engine(url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as db:
        rows = await report_cbl_source_identity_resolution(
            db,
            user_id=args.user_id,
            source_list_id=args.source_list_id,
        )
        payload = {
            "source_list_id": args.source_list_id,
            "user_id": args.user_id,
            "entry_count": len(rows),
            "resolution_complete": resolution_is_complete(rows),
            "rows": [row_to_dict(row) for row in rows],
        }
        await db.rollback()
        print(json.dumps(payload, indent=2, sort_keys=True))
    await engine.dispose()


def main() -> None:
    """Parse CLI arguments and print a read-only identity-resolution report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--source-list-id", type=int, required=True)
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()

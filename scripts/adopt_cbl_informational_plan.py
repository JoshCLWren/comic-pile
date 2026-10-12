#!/usr/bin/env python3
"""Adopt an imported CBL list as an informational Reading Plan.

Does not compile inferred gates and does not insert Dependencies. Production
is never the default target. Apply requires
``ADOPT-CBL-INFORMATIONAL-NO-INFERRED-GATES`` and a local database URL.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONFIRMATION = "ADOPT-CBL-INFORMATIONAL-NO-INFERRED-GATES"


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
    from app.services.cbl_informational_plan_adoption import (
        adopt_cbl_list_as_informational_plan,
    )
    from scripts.database_target_safety import require_local_database_url

    url = _async_url(_require_database_url(args.database_url))
    if args.command == "apply":
        require_local_database_url(args.database_url)
        if args.confirm != CONFIRMATION:
            raise SystemExit(f"apply requires --confirm {CONFIRMATION}")
    engine = create_async_engine(url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as db:
        plan = await adopt_cbl_list_as_informational_plan(
            db,
            user_id=args.user_id,
            source_list_id=args.source_list_id,
            plan_name=args.plan_name,
        )
        payload = {
            "plan_id": plan.id,
            "name": plan.name,
            "ordering_mode": plan.ordering_mode,
            "member_count": len(plan.nodes_json),
        }
        if args.command == "apply":
            await db.commit()
            print(f"applied informational plan {payload}")
        else:
            await db.rollback()
            print(f"dry-run informational plan {payload}")
    await engine.dispose()


def main() -> None:
    """Parse CLI arguments and run dry-run or local apply."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("dry-run", "apply"))
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--source-list-id", type=int, required=True)
    parser.add_argument("--plan-name", required=True)
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()

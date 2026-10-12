#!/usr/bin/env python3
r"""Align Reading Plan membership to nodes_json without compiling strict rules (#3486).

``nodes_json`` is the intended membership. This command copies existing Issue
refs into ``reading_plan_issues`` and never calls the strict compiler, so a
drifted strict plan is not re-saved into a blanket of adjacent blockers.

Every mode requires ``--database-url``. Production is never the default
target. Apply requires ``--confirm MEMBERSHIP-JSON-AUTHORITATIVE``.

Examples::

    python scripts/repair_reading_plan_membership.py dry-run
        --database-url "$CLONE_DATABASE_URL" --plan-id 20

    python scripts/repair_reading_plan_membership.py apply
        --database-url "$CLONE_DATABASE_URL" --plan-id 20
        --confirm MEMBERSHIP-JSON-AUTHORITATIVE
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import json
from pathlib import Path
import sys
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONFIRMATION = "MEMBERSHIP-JSON-AUTHORITATIVE"


def _async_url(raw: str) -> str:
    """Normalize a Neon or libpq URL into an asyncpg SQLAlchemy URL."""
    url = raw
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    elif url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://") :]
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.pop("channel_binding", None)
    sslmode = query.pop("sslmode", None)
    if sslmode in {"require", "verify-full", "verify-ca"} or "ssl" not in query:
        query["ssl"] = "require"
    return urlunparse(parsed._replace(query=urlencode(query)))


def _require_database_url(value: str | None) -> str:
    """Refuse implicit production URL discovery."""
    if value is None or not value.strip():
        raise SystemExit(
            "every command requires an explicit --database-url; "
            "production is never the default target"
        )
    return value.strip()


@asynccontextmanager
async def _session(database_url: str) -> AsyncIterator[AsyncSession]:
    """Open one explicit-URL async session and dispose the engine afterwards."""
    engine = create_async_engine(_async_url(database_url), pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


async def _run(mode: str, database_url: str, plan_id: int, confirm: str | None) -> int:
    """Execute dry-run or apply for one plan id."""
    from app.models.continuity_plan import ContinuityPlan
    from app.services.reading_plan_normalization import (
        dry_run_plan_membership_reconcile,
        membership_report_to_dict,
        reconcile_plan_membership_from_nodes,
    )

    if mode == "apply" and confirm != CONFIRMATION:
        raise SystemExit(f"apply requires --confirm {CONFIRMATION}")
    async with _session(database_url) as db:
        plan = await db.get(ContinuityPlan, plan_id)
        if plan is None:
            raise SystemExit(f"plan {plan_id} not found")
        if mode == "dry-run":
            report = await dry_run_plan_membership_reconcile(db, plan=plan)
            await db.rollback()
        else:
            report = await reconcile_plan_membership_from_nodes(db, plan=plan)
            await db.commit()
    payload = membership_report_to_dict(report)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def main() -> int:
    """Parse CLI arguments and run the requested membership repair mode."""
    parser = argparse.ArgumentParser(
        description="Repair Reading Plan membership from nodes_json without compiling"
    )
    parser.add_argument("mode", choices=("dry-run", "apply"))
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--plan-id", type=int, required=True)
    parser.add_argument("--confirm", default=None)
    args = parser.parse_args()
    return asyncio.run(
        _run(
            args.mode,
            _require_database_url(args.database_url),
            args.plan_id,
            args.confirm,
        )
    )


if __name__ == "__main__":
    sys.exit(main())

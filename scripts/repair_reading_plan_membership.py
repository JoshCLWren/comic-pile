#!/usr/bin/env python3
r"""Trim Reading Plan JSON leftovers to membership without compiling (#3486).

``reading_plan_issues`` is the intended membership. Extra issue nodes in
``nodes_json`` are stale leftovers from series removals. This command trims
the plan record and its source order to that table and never calls the
strict compiler, so dropped series are not restored or compiled.

Every mode requires ``--database-url``. Production is never the default
target. This script does not create Neon branches. Apply requires
``--confirm MEMBERSHIP-TABLE-AUTHORITATIVE`` and writes a receipt whose
``backup`` is the rollback payload.

Rollback restores previous ``nodes_json``, ``reading_plan_sources``, and
``reading_plan_source_placements``. ``reading_plan_issues`` is unchanged
by apply and by rollback.

Examples::

    python scripts/repair_reading_plan_membership.py dry-run
        --database-url "$CLONE_DATABASE_URL" --plan-id 20

    python scripts/repair_reading_plan_membership.py apply
        --database-url "$CLONE_DATABASE_URL" --plan-id 20
        --receipt /tmp/plan-20-membership-trim.json
        --confirm MEMBERSHIP-TABLE-AUTHORITATIVE

    python scripts/repair_reading_plan_membership.py rollback
        --database-url "$CLONE_DATABASE_URL" --plan-id 20
        --receipt /tmp/plan-20-membership-trim.json
        --confirm MEMBERSHIP-TABLE-AUTHORITATIVE
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

CONFIRMATION = "MEMBERSHIP-TABLE-AUTHORITATIVE"


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


def _write_json(path: Path, payload: dict[str, object]) -> None:
    """Write a receipt or dry-run report as pretty JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, object]:
    """Load a previously written apply receipt."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"expected JSON object in {path}")
    return payload


async def _run(
    mode: str,
    database_url: str,
    plan_id: int,
    confirm: str | None,
    receipt_path: Path | None,
) -> int:
    """Execute dry-run, apply, or rollback for one plan id."""
    from app.models.continuity_plan import ContinuityPlan
    from app.services.reading_plan_normalization import (
        backup_from_dict,
        dry_run_plan_membership_reconcile,
        membership_report_to_dict,
        reconcile_plan_record_to_membership,
        restore_plan_record_from_backup,
    )

    if mode in {"apply", "rollback"} and confirm != CONFIRMATION:
        raise SystemExit(f"{mode} requires --confirm {CONFIRMATION}")
    if mode in {"apply", "rollback"} and receipt_path is None:
        raise SystemExit(f"{mode} requires --receipt PATH")
    async with _session(database_url) as db:
        plan = await db.get(ContinuityPlan, plan_id)
        if plan is None:
            raise SystemExit(f"plan {plan_id} not found")
        if mode == "dry-run":
            report = await dry_run_plan_membership_reconcile(db, plan=plan)
            await db.rollback()
            payload = membership_report_to_dict(report)
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        if mode == "apply":
            report = await reconcile_plan_record_to_membership(db, plan=plan)
            await db.commit()
            payload = membership_report_to_dict(report, include_backup=True)
            assert receipt_path is not None
            _write_json(receipt_path, payload)
            print(json.dumps(membership_report_to_dict(report), indent=2, sort_keys=True))
            return 0
        receipt = _read_json(receipt_path) if receipt_path is not None else {}
        backup_payload = receipt.get("backup")
        if not isinstance(backup_payload, dict):
            raise SystemExit("receipt is missing backup; cannot rollback")
        receipt_plan_id = receipt.get("plan_id")
        if receipt_plan_id != plan_id:
            raise SystemExit(
                f"receipt plan_id {receipt_plan_id} does not match --plan-id {plan_id}"
            )
        await restore_plan_record_from_backup(
            db, plan=plan, backup=backup_from_dict(backup_payload)
        )
        await db.commit()
    print(json.dumps({"plan_id": plan_id, "rolled_back": True}, indent=2, sort_keys=True))
    return 0


def main() -> int:
    """Parse CLI arguments and run the requested membership repair mode."""
    parser = argparse.ArgumentParser(
        description=(
            "Trim Reading Plan JSON leftovers to membership without compiling"
        )
    )
    parser.add_argument("mode", choices=("dry-run", "apply", "rollback"))
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--plan-id", type=int, required=True)
    parser.add_argument("--confirm", default=None)
    parser.add_argument("--receipt", type=Path, default=None)
    args = parser.parse_args()
    return asyncio.run(
        _run(
            args.mode,
            _require_database_url(args.database_url),
            args.plan_id,
            args.confirm,
            args.receipt,
        )
    )


if __name__ == "__main__":
    sys.exit(main())

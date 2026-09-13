#!/usr/bin/env python3
"""Guarded operator CLI for the Step 23B legacy Reading Order migration.

This command never discovers a production database URL. Every mode requires
``--database-url``. Apply and rollback also require the Step 23B confirmation
string and the reviewed snapshot or receipt token.

Examples:
    python scripts/legacy_reading_order_step23b_migration.py dry-run \
        --database-url "$CLONE_DATABASE_URL" \
        --output /tmp/step23b-dry-run.json

    python scripts/legacy_reading_order_step23b_migration.py apply \
        --database-url "$CLONE_DATABASE_URL" \
        --accepted-snapshot-token 6cfa01ccc82f33c4e0fc7a23d9b7d4e4b32a66a7aa13bbbfd50bc633e38bdf7c \
        --confirm STEP23B-LEGACY-READING-ORDERS \
        --receipt /tmp/step23b-receipt.json

    python scripts/legacy_reading_order_step23b_migration.py rollback \
        --database-url "$CLONE_DATABASE_URL" \
        --receipt /tmp/step23b-receipt.json \
        --confirm STEP23B-LEGACY-READING-ORDERS \
        --rollback-guard-token "$RECEIPT_GUARD_TOKEN"
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import json
from pathlib import Path
import sys
from typing import cast
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.legacy_reading_order_production_migration import (  # noqa: E402
    REVIEWED_STEP23A_SNAPSHOT_TOKEN,
    MigrationInvariantError,
    apply_legacy_reading_order_migration,
    build_legacy_reading_order_dry_run,
    rollback_legacy_reading_order_migration,
)

CONFIRMATION = "STEP23B-LEGACY-READING-ORDERS"


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


def _write_json(path: Path, payload: dict[str, object]) -> None:
    """Write one JSON object with stable formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, object]:
    """Read one JSON object from disk."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MigrationInvariantError(f"expected JSON object in {path}")
    return cast(dict[str, object], value)


def _require_confirmation(value: str | None) -> None:
    """Refuse apply/rollback without the unique Step 23B confirmation string."""
    if value != CONFIRMATION:
        raise MigrationInvariantError(
            f"apply/rollback requires --confirm {CONFIRMATION}"
        )


def _require_database_url(value: str | None) -> str:
    """Refuse implicit production URL discovery."""
    if value is None or not value.strip():
        raise MigrationInvariantError(
            "every Step 23B command requires an explicit --database-url; "
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


async def _dry_run(database_url: str, output: Path) -> int:
    """Run the read-only Step 23A/23B preflight and write the report."""
    async with _session(database_url) as db:
        report = await build_legacy_reading_order_dry_run(db)
        await db.rollback()
    _write_json(output, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("ok") is True else 2


async def _apply(
    database_url: str,
    accepted_snapshot_token: str | None,
    confirm: str | None,
    receipt_path: Path,
) -> int:
    """Apply the migration only when the reviewed snapshot token still matches."""
    _require_confirmation(confirm)
    if accepted_snapshot_token != REVIEWED_STEP23A_SNAPSHOT_TOKEN:
        raise MigrationInvariantError(
            "apply requires --accepted-snapshot-token to equal the reviewed "
            f"Step 23A token {REVIEWED_STEP23A_SNAPSHOT_TOKEN}. "
            "The reviewed Step 23A snapshot is stale and a new preflight/review "
            "is required."
        )
    async with _session(database_url) as db:
        try:
            receipt = await apply_legacy_reading_order_migration(
                db,
                accepted_snapshot_token=accepted_snapshot_token,
                require_reviewed_token=True,
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    _write_json(receipt_path, receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


async def _rollback(
    database_url: str,
    receipt_path: Path,
    confirm: str | None,
    rollback_guard_token: str | None,
) -> int:
    """Restore the exact receipt-captured compatibility state."""
    _require_confirmation(confirm)
    receipt = _read_json(receipt_path)
    expected_guard = receipt.get("rollback_guard_token")
    if rollback_guard_token != expected_guard:
        raise MigrationInvariantError(
            "rollback requires --rollback-guard-token to equal the apply receipt "
            "rollback_guard_token"
        )
    async with _session(database_url) as db:
        try:
            result = await rollback_legacy_reading_order_migration(db, receipt=receipt)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _parser() -> argparse.ArgumentParser:
    """Build the Step 23B operator parser."""
    parser = argparse.ArgumentParser(
        description="Step 23B guarded legacy Reading Order migration"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    dry_run = subparsers.add_parser("dry-run", help="read-only Step 23A re-preflight")
    dry_run.add_argument("--database-url", required=True)
    dry_run.add_argument("--output", type=Path, required=True)

    apply_parser = subparsers.add_parser("apply", help="apply only the reviewed snapshot")
    apply_parser.add_argument("--database-url", required=True)
    apply_parser.add_argument("--accepted-snapshot-token", required=True)
    apply_parser.add_argument("--confirm")
    apply_parser.add_argument("--receipt", type=Path, required=True)

    rollback = subparsers.add_parser(
        "rollback",
        help="restore captured legacy compatibility state from an apply receipt",
    )
    rollback.add_argument("--database-url", required=True)
    rollback.add_argument("--receipt", type=Path, required=True)
    rollback.add_argument("--confirm")
    rollback.add_argument("--rollback-guard-token", required=True)
    return parser


async def _main(argv: list[str] | None = None) -> int:
    """Dispatch one explicit-URL Step 23B command."""
    args = _parser().parse_args(argv)
    database_url = _require_database_url(getattr(args, "database_url", None))
    if args.command == "dry-run":
        return await _dry_run(database_url, args.output)
    if args.command == "apply":
        return await _apply(
            database_url,
            args.accepted_snapshot_token,
            args.confirm,
            args.receipt,
        )
    if args.command == "rollback":
        return await _rollback(
            database_url,
            args.receipt,
            args.confirm,
            args.rollback_guard_token,
        )
    raise AssertionError(f"unhandled command {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(_main()))
    except MigrationInvariantError as exc:
        print(f"Step 23B migration refused: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

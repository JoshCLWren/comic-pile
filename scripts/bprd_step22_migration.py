#!/usr/bin/env python3
"""Guarded operator CLI for the Step 22 B.P.R.D. production migration.

Examples:
    python scripts/bprd_step22_migration.py dry-run --output /tmp/bprd-step22.json
    python scripts/bprd_step22_migration.py apply \
        --snapshot /tmp/bprd-step22.json \
        --receipt /tmp/bprd-step22-receipt.json \
        --confirm STEP22-BPRD
    python scripts/bprd_step22_migration.py rollback \
        --snapshot /tmp/bprd-step22.json \
        --receipt /tmp/bprd-step22-receipt.json \
        --confirm STEP22-BPRD
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import AsyncSessionLocal  # noqa: E402
from app.services.bprd_production_migration import (  # noqa: E402
    MigrationInvariantError,
    apply_bprd_migration,
    build_bprd_dry_run,
    rollback_bprd_migration,
)

CONFIRMATION = "STEP22-BPRD"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MigrationInvariantError(f"expected JSON object in {path}")
    return value


def _require_confirmation(value: str | None) -> None:
    if value != CONFIRMATION:
        raise MigrationInvariantError(
            f"apply/rollback requires --confirm {CONFIRMATION}"
        )


async def _dry_run(output: Path) -> int:
    async with AsyncSessionLocal() as db:
        report = await build_bprd_dry_run(db)
        await db.rollback()
    _write_json(output, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] is True else 2


async def _apply(snapshot_path: Path, receipt_path: Path, confirm: str | None) -> int:
    _require_confirmation(confirm)
    snapshot = _read_json(snapshot_path)
    async with AsyncSessionLocal() as db:
        try:
            receipt = await apply_bprd_migration(db, snapshot=snapshot)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    _write_json(receipt_path, receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


async def _rollback(
    snapshot_path: Path,
    receipt_path: Path,
    confirm: str | None,
) -> int:
    _require_confirmation(confirm)
    snapshot = _read_json(snapshot_path)
    receipt = _read_json(receipt_path)
    async with AsyncSessionLocal() as db:
        try:
            result = await rollback_bprd_migration(
                db,
                snapshot=snapshot,
                receipt=receipt,
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Step 22 B.P.R.D. Reading Plan production migration"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    dry_run = subparsers.add_parser("dry-run", help="read-only production preflight")
    dry_run.add_argument("--output", type=Path, required=True)

    apply_parser = subparsers.add_parser("apply", help="apply an exact clean snapshot")
    apply_parser.add_argument("--snapshot", type=Path, required=True)
    apply_parser.add_argument("--receipt", type=Path, required=True)
    apply_parser.add_argument("--confirm")

    rollback = subparsers.add_parser(
        "rollback",
        help="restore captured legacy edges after a failed cutover",
    )
    rollback.add_argument("--snapshot", type=Path, required=True)
    rollback.add_argument("--receipt", type=Path, required=True)
    rollback.add_argument("--confirm")
    return parser


async def _main() -> int:
    args = _parser().parse_args()
    if args.command == "dry-run":
        return await _dry_run(args.output)
    if args.command == "apply":
        return await _apply(args.snapshot, args.receipt, args.confirm)
    if args.command == "rollback":
        return await _rollback(args.snapshot, args.receipt, args.confirm)
    raise AssertionError(f"unhandled command {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(_main()))
    except MigrationInvariantError as exc:
        print(f"Step 22 migration refused: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

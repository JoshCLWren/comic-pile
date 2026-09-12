#!/usr/bin/env python3
"""Operator CLI for Step 27 source-backed reader-order migrations."""
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
from app.services.source_backed_reader_order_migration import (  # noqa: E402
    PRODUCTION_ABSOLUTE_UNIVERSE_SPEC,
    MigrationInvariantError,
    SourceBackedReaderOrderSpec,
    apply_source_backed_reader_order_migration,
    build_source_backed_reader_order_dry_run,
)

CONFIRMATION = "STEP27-READER-ORDER"
MANIFESTS: dict[str, SourceBackedReaderOrderSpec] = {
    "absolute-universe": PRODUCTION_ABSOLUTE_UNIVERSE_SPEC,
}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MigrationInvariantError(f"expected JSON object in {path}")
    return value


def _require_confirmation(value: str | None) -> None:
    if value != CONFIRMATION:
        raise MigrationInvariantError(f"apply requires --confirm {CONFIRMATION}")


async def _dry_run(manifest: str, output: Path) -> int:
    async with AsyncSessionLocal() as db:
        report = await build_source_backed_reader_order_dry_run(db, MANIFESTS[manifest])
        await db.rollback()
    _write_json(output, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] is True else 2


async def _apply(manifest: str, snapshot_path: Path, receipt_path: Path, confirm: str | None) -> int:
    _require_confirmation(confirm)
    snapshot = _read_json(snapshot_path)
    async with AsyncSessionLocal() as db:
        try:
            receipt = await apply_source_backed_reader_order_migration(
                db,
                snapshot=snapshot,
                spec=MANIFESTS[manifest],
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    _write_json(receipt_path, receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Step 27 source-backed reader-order migration")
    parser.add_argument("--manifest", choices=sorted(MANIFESTS), required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    dry = subparsers.add_parser("dry-run", help="read-only production preflight")
    dry.add_argument("--output", type=Path, required=True)
    apply_parser = subparsers.add_parser("apply", help="apply an exact clean snapshot")
    apply_parser.add_argument("--snapshot", type=Path, required=True)
    apply_parser.add_argument("--receipt", type=Path, required=True)
    apply_parser.add_argument("--confirm")
    return parser


async def _main() -> int:
    args = _parser().parse_args()
    if args.command == "dry-run":
        return await _dry_run(args.manifest, args.output)
    if args.command == "apply":
        return await _apply(args.manifest, args.snapshot, args.receipt, args.confirm)
    raise AssertionError(f"unhandled command {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(_main()))
    except MigrationInvariantError as exc:
        print(f"Step 27 migration refused: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

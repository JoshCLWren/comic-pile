#!/usr/bin/env python3
"""Operator CLI for Crossover reader-order migrations (#3038)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import AsyncSessionLocal  # noqa: E402
from app.services.crossover_reading_order_migration import (  # noqa: E402
    CROSSOVER_MIGRATION_CONFIRMATION,
    CrossoverReadingOrderSpec,
    MigrationInvariantError,
    apply_crossover_reading_order_migration,
    build_crossover_reading_order_dry_run,
    classify_crossover_group,
    crossover_content_hash,
    inventory_crossover_reader_orders,
)
from app.models.dependency_group import (  # noqa: E402
    DependencyGroup,
    DependencyGroupMembership,
)
from sqlalchemy import select  # noqa: E402


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _stage_durable_json(path: Path, payload: dict[str, Any]) -> Path:
    """Write and fsync a same-directory pending receipt before DB commit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_pending = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".pending",
        dir=path.parent,
        text=True,
    )
    pending = Path(raw_pending)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        pending.unlink(missing_ok=True)
        raise
    return pending


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MigrationInvariantError(f"expected JSON object in {path}")
    return value


async def _derive_spec(
    user_id: int,
    group_id: int,
    plan_name: str | None,
    expected_hash: str | None,
    expected_positions: int | None,
) -> CrossoverReadingOrderSpec:
    """Build a spec, deriving unset manifest fields from live state."""
    async with AsyncSessionLocal() as db:
        group = await db.get(DependencyGroup, group_id)
        if group is None or group.user_id != user_id:
            raise MigrationInvariantError(f"crossover group {group_id} missing or not owned")
        name = plan_name or group.name
        memberships = list(
            (
                await db.execute(
                    select(DependencyGroupMembership).where(
                        DependencyGroupMembership.group_id == group.id
                    )
                )
            )
            .scalars()
            .all()
        )
        ordered = sorted(
            [
                (m.issue_id, m.sequence_order)
                for m in memberships
                if m.issue_id is not None and m.sequence_order is not None
            ],
            key=lambda row: row[1],
        )
        derived_hash = crossover_content_hash(
            [(0, issue_id, seq) for issue_id, seq in ordered]
        )
        await db.rollback()
    return CrossoverReadingOrderSpec(
        user_id=user_id,
        dependency_group_id=group_id,
        plan_name=name,
        expected_content_hash=expected_hash or derived_hash,
        expected_positions=len(ordered) if expected_positions is None else expected_positions,
    )


async def _inventory(user_id: int) -> int:
    async with AsyncSessionLocal() as db:
        rows = await inventory_crossover_reader_orders(db, user_id=user_id)
        await db.rollback()
    for row in rows:
        print(
            f"#{row['group_id']} {row['group_name']}: "
            f"{row['classification']} ({row['position_count']} positions) — {row['reason']}"
        )
    return 0


async def _classify(user_id: int, group_id: int) -> int:
    async with AsyncSessionLocal() as db:
        result = await classify_crossover_group(db, user_id=user_id, group_id=group_id)
        await db.rollback()
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


async def _dry_run(
    user_id: int,
    group_id: int,
    plan_name: str | None,
    expected_hash: str | None,
    expected_positions: int | None,
    output: Path,
) -> int:
    spec = await _derive_spec(user_id, group_id, plan_name, expected_hash, expected_positions)
    async with AsyncSessionLocal() as db:
        report = await build_crossover_reading_order_dry_run(db, spec)
        await db.rollback()
    _write_json(output, report)
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    if expected_hash is None or expected_positions is None:
        print(
            "\nNOTE: manifest fields were derived from live state. Freeze "
            f"expected_hash={spec.expected_content_hash} and "
            f"expected_positions={spec.expected_positions} before apply.",
        )
    return 0 if report["ok"] is True else 2


async def _apply(
    user_id: int,
    group_id: int,
    plan_name: str | None,
    expected_hash: str | None,
    expected_positions: int | None,
    snapshot_path: Path,
    receipt_path: Path,
    confirm: str | None,
) -> int:
    if confirm != CROSSOVER_MIGRATION_CONFIRMATION:
        raise MigrationInvariantError(
            f"apply requires --confirm {CROSSOVER_MIGRATION_CONFIRMATION}"
        )
    if expected_hash is None or expected_positions is None:
        raise MigrationInvariantError(
            "apply requires frozen --expected-hash and --expected-positions"
        )
    spec = await _derive_spec(user_id, group_id, plan_name, expected_hash, expected_positions)
    snapshot = _read_json(snapshot_path)
    if snapshot.get("manifest", {}).get("expected_content_hash") != spec.expected_content_hash:
        raise MigrationInvariantError("snapshot manifest does not match frozen spec")
    pending_receipt: Path | None = None
    async with AsyncSessionLocal() as db:
        try:
            receipt = await apply_crossover_reading_order_migration(
                db, snapshot=snapshot, spec=spec
            )
            pending_receipt = _stage_durable_json(receipt_path, receipt)
            await db.commit()
        except Exception:
            await db.rollback()
            if pending_receipt is not None:
                pending_receipt.unlink(missing_ok=True)
            raise
    if pending_receipt is None:
        raise MigrationInvariantError("migration committed without a staged receipt")
    try:
        pending_receipt.replace(receipt_path)
    except OSError as exc:
        raise MigrationInvariantError(
            "migration committed, but the durable receipt could not be published; "
            f"recovery receipt remains at {pending_receipt}"
        ) from exc
    print(json.dumps(receipt, indent=2, sort_keys=True, default=str))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Crossover reader-order migration (#3038)"
    )
    parser.add_argument("--user-id", type=int, default=1)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("inventory", help="classify every crossover group")
    classify = subparsers.add_parser("classify", help="classify one crossover group")
    classify.add_argument("--group-id", type=int, required=True)

    def _add_spec_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--group-id", type=int, required=True)
        p.add_argument("--plan-name", default=None)
        p.add_argument("--expected-hash", default=None)
        p.add_argument("--expected-positions", type=int, default=None)

    dry = subparsers.add_parser("dry-run", help="read-only migration preflight")
    _add_spec_args(dry)
    dry.add_argument("--output", type=Path, required=True)
    apply_parser = subparsers.add_parser("apply", help="apply an exact clean snapshot")
    _add_spec_args(apply_parser)
    apply_parser.add_argument("--snapshot", type=Path, required=True)
    apply_parser.add_argument("--receipt", type=Path, required=True)
    apply_parser.add_argument("--confirm", default=None)
    return parser


async def _main() -> int:
    args = _parser().parse_args()
    if args.command == "inventory":
        return await _inventory(args.user_id)
    if args.command == "classify":
        return await _classify(args.user_id, args.group_id)
    if args.command == "dry-run":
        return await _dry_run(
            args.user_id,
            args.group_id,
            args.plan_name,
            args.expected_hash,
            args.expected_positions,
            args.output,
        )
    if args.command == "apply":
        return await _apply(
            args.user_id,
            args.group_id,
            args.plan_name,
            args.expected_hash,
            args.expected_positions,
            args.snapshot,
            args.receipt,
            args.confirm,
        )
    raise AssertionError(f"unhandled command {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(_main()))
    except MigrationInvariantError as exc:
        print(f"Crossover migration refused: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

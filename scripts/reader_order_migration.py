#!/usr/bin/env python3
"""Operator CLI for Step 27 reader-order migrations."""

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


def _load_application_symbols():
    """Import project modules after making direct script execution import-safe."""
    from app.database import AsyncSessionLocal
    from app.services.explicit_reader_order_migration import (
        PRODUCTION_EXPLICIT_READER_ORDER_SPECS,
        apply_explicit_reader_order_migration,
    )
    from app.services.reader_order_cutover import build_reader_order_cutover_audit
    from app.services.reader_order_migration_coordinator import build_manifest_report
    from app.services.source_backed_reader_order_migration import (
        PRODUCTION_SOURCE_BACKED_SPECS,
        apply_source_backed_reader_order_migration,
    )
    from app.services.ultimate_universe_production_migration import (
        MigrationInvariantError,
    )

    return (
        AsyncSessionLocal,
        PRODUCTION_EXPLICIT_READER_ORDER_SPECS,
        apply_explicit_reader_order_migration,
        build_reader_order_cutover_audit,
        build_manifest_report,
        PRODUCTION_SOURCE_BACKED_SPECS,
        apply_source_backed_reader_order_migration,
        MigrationInvariantError,
    )


(
    AsyncSessionLocal,
    PRODUCTION_EXPLICIT_READER_ORDER_SPECS,
    apply_explicit_reader_order_migration,
    build_reader_order_cutover_audit,
    build_manifest_report,
    PRODUCTION_SOURCE_BACKED_SPECS,
    apply_source_backed_reader_order_migration,
    MigrationInvariantError,
) = _load_application_symbols()

CONFIRMATION = "STEP27-READER-ORDER"
SOURCE_MANIFESTS = PRODUCTION_SOURCE_BACKED_SPECS
EXPLICIT_MANIFESTS = PRODUCTION_EXPLICIT_READER_ORDER_SPECS
ALL_MANIFESTS = sorted({*SOURCE_MANIFESTS, *EXPLICIT_MANIFESTS})


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


def _require_confirmation(value: str | None) -> None:
    if value != CONFIRMATION:
        raise MigrationInvariantError(f"apply requires --confirm {CONFIRMATION}")


async def _build_report(manifest: str) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        report = await build_manifest_report(
            db,
            manifest=manifest,
            source_manifests=SOURCE_MANIFESTS,
            explicit_manifests=EXPLICIT_MANIFESTS,
        )
        await db.rollback()
    return report


async def _dry_run(manifest: str, output: Path) -> int:
    report = await _build_report(manifest)
    _write_json(output, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] in {"safe-to-migrate", "already-migrated"} else 2


async def _batch_dry_run(
    manifests: list[str],
    output_dir: Path,
    summary_path: Path,
) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for manifest in manifests:
        report = await _build_report(manifest)
        status = str(report["status"])
        payload = report
        output = output_dir / f"{manifest}.json"
        _write_json(output, payload)
        rows.append(
            {
                "manifest": manifest,
                "status": status,
                "ok": status in {"safe-to-migrate", "already-migrated"},
                "errors": report.get("errors", []),
                "snapshot_token": report.get("snapshot_token"),
                "standalone_prerequisite_count": len(
                    report.get("preserved_standalone_dependencies", [])
                ),
                "output": str(output),
            }
        )
    summary = {
        "manifests": rows,
        "safe_to_migrate": [
            row["manifest"] for row in rows if row["status"] == "safe-to-migrate"
        ],
        "blocked_by_identity_or_source": [
            row["manifest"]
            for row in rows
            if row["status"] == "blocked-by-identity-or-source"
        ],
        "blocked_by_needs_review": [
            row["manifest"]
            for row in rows
            if row["status"] == "blocked-by-needs-review"
        ],
        "behavior_mismatch": [
            row["manifest"] for row in rows if row["status"] == "behavior-mismatch"
        ],
        "already_migrated": [
            row["manifest"] for row in rows if row["status"] == "already-migrated"
        ],
        "standalone_prerequisite_state": {
            row["manifest"]: row["standalone_prerequisite_count"] for row in rows
        },
    }
    summary["blocked"] = [
        row["manifest"]
        for row in rows
        if row["status"] not in {"safe-to-migrate", "already-migrated"}
    ]
    _write_json(summary_path, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if not summary["blocked"] else 2


async def _apply(
    manifest: str,
    snapshot_path: Path,
    receipt_path: Path,
    confirm: str | None,
) -> int:
    _require_confirmation(confirm)
    snapshot = _read_json(snapshot_path)
    pending_receipt: Path | None = None
    async with AsyncSessionLocal() as db:
        try:
            if manifest in SOURCE_MANIFESTS:
                receipt = await apply_source_backed_reader_order_migration(
                    db,
                    snapshot=snapshot,
                    spec=SOURCE_MANIFESTS[manifest],
                )
            else:
                receipt = await apply_explicit_reader_order_migration(
                    db,
                    snapshot=snapshot,
                    spec=EXPLICIT_MANIFESTS[manifest],
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

    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


async def _batch_apply(
    summary_path: Path,
    receipt_path: Path,
    confirm: str | None,
) -> int:
    """Apply every clean manifest from one exact batch dry-run transactionally."""
    _require_confirmation(confirm)
    summary = _read_json(summary_path)
    raw_rows = summary.get("manifests")
    if not isinstance(raw_rows, list):
        raise MigrationInvariantError("batch summary has no manifest rows")

    pending_receipt: Path | None = None
    batch_receipt: dict[str, Any] | None = None
    async with AsyncSessionLocal() as db:
        try:
            applied: list[dict[str, Any]] = []
            skipped: list[dict[str, str]] = []
            for raw_row in raw_rows:
                if not isinstance(raw_row, dict):
                    raise MigrationInvariantError("batch summary contains a malformed row")
                manifest = str(raw_row.get("manifest") or "")
                status = str(raw_row.get("status") or "")
                if manifest not in ALL_MANIFESTS:
                    raise MigrationInvariantError(f"unknown manifest in batch: {manifest!r}")
                if status != "safe-to-migrate":
                    skipped.append({"manifest": manifest, "status": status})
                    continue

                output = raw_row.get("output")
                if not isinstance(output, str):
                    raise MigrationInvariantError(
                        f"safe manifest {manifest} has no snapshot path"
                    )
                snapshot = _read_json(Path(output))
                if (
                    snapshot.get("status") != "safe-to-migrate"
                    or snapshot.get("snapshot_token") != raw_row.get("snapshot_token")
                ):
                    raise MigrationInvariantError(
                        f"batch snapshot metadata changed for {manifest}"
                    )
                if manifest in SOURCE_MANIFESTS:
                    result = await apply_source_backed_reader_order_migration(
                        db,
                        snapshot=snapshot,
                        spec=SOURCE_MANIFESTS[manifest],
                    )
                else:
                    result = await apply_explicit_reader_order_migration(
                        db,
                        snapshot=snapshot,
                        spec=EXPLICIT_MANIFESTS[manifest],
                    )
                applied.append({"manifest": manifest, **result})

            cutover = await build_reader_order_cutover_audit(db, user_id=1)
            batch_receipt = {
                "source_summary": str(summary_path),
                "applied": applied,
                "skipped": skipped,
                "cutover_audit": cutover,
                "runtime_switch_instruction": (
                    "Set LEGACY_DEPENDENCY_BLOCKING_ENABLED=false only when "
                    "cutover_audit.runtime_cutover_safe is true."
                ),
            }
            pending_receipt = _stage_durable_json(receipt_path, batch_receipt)
            await db.commit()
        except Exception:
            await db.rollback()
            if pending_receipt is not None:
                pending_receipt.unlink(missing_ok=True)
            raise

    if pending_receipt is None or batch_receipt is None:
        raise MigrationInvariantError("batch committed without a staged receipt")
    try:
        pending_receipt.replace(receipt_path)
    except OSError as exc:
        raise MigrationInvariantError(
            "batch committed, but the durable receipt could not be published; "
            f"recovery receipt remains at {pending_receipt}"
        ) from exc
    print(json.dumps(batch_receipt, indent=2, sort_keys=True))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Step 27 reader-order migration")
    subparsers = parser.add_subparsers(dest="command", required=True)

    dry = subparsers.add_parser("dry-run", help="read-only preflight for one manifest")
    dry.add_argument("--manifest", choices=ALL_MANIFESTS, required=True)
    dry.add_argument("--output", type=Path, required=True)

    batch = subparsers.add_parser(
        "batch-dry-run",
        help="read-only preflight for every registered Step 27 manifest",
    )
    batch.add_argument(
        "--manifest",
        action="append",
        choices=ALL_MANIFESTS,
        dest="manifests",
        help="manifest to include; repeat as needed; defaults to every manifest",
    )
    batch.add_argument("--output-dir", type=Path, required=True)
    batch.add_argument("--summary", type=Path, required=True)

    apply_parser = subparsers.add_parser(
        "apply",
        help="apply an exact clean snapshot for one manifest",
    )
    apply_parser.add_argument("--manifest", choices=ALL_MANIFESTS, required=True)
    apply_parser.add_argument("--snapshot", type=Path, required=True)
    apply_parser.add_argument("--receipt", type=Path, required=True)
    apply_parser.add_argument("--confirm")

    batch_apply = subparsers.add_parser(
        "batch-apply",
        help="apply every safe snapshot from an exact batch summary in one transaction",
    )
    batch_apply.add_argument("--summary", type=Path, required=True)
    batch_apply.add_argument("--receipt", type=Path, required=True)
    batch_apply.add_argument("--confirm")

    cutover = subparsers.add_parser(
        "cutover-audit",
        help="read-only release gate for raw Dependency Roll blocking",
    )
    cutover.add_argument("--user-id", type=int, default=1)
    cutover.add_argument("--output", type=Path, required=True)
    return parser


async def _main() -> int:
    args = _parser().parse_args()
    if args.command == "dry-run":
        return await _dry_run(args.manifest, args.output)
    if args.command == "batch-dry-run":
        manifests = args.manifests or ALL_MANIFESTS
        return await _batch_dry_run(manifests, args.output_dir, args.summary)
    if args.command == "apply":
        return await _apply(
            args.manifest,
            args.snapshot,
            args.receipt,
            args.confirm,
        )
    if args.command == "batch-apply":
        return await _batch_apply(args.summary, args.receipt, args.confirm)
    if args.command == "cutover-audit":
        async with AsyncSessionLocal() as db:
            report = await build_reader_order_cutover_audit(
                db,
                user_id=args.user_id,
            )
            await db.rollback()
        _write_json(args.output, report)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["runtime_cutover_safe"] is True else 2
    raise AssertionError(f"unhandled command {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(_main()))
    except MigrationInvariantError as exc:
        print(f"Step 27 migration refused: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

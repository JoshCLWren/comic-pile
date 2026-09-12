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

from app.database import AsyncSessionLocal  # noqa: E402
from app.services.explicit_reader_order_migration import (  # noqa: E402
    PRODUCTION_EXPLICIT_READER_ORDER_SPECS,
    ExplicitReaderOrderSpec,
    apply_explicit_reader_order_migration,
    build_explicit_reader_order_dry_run,
)
from app.services.source_backed_reader_order_migration import (  # noqa: E402
    PRODUCTION_ABSOLUTE_UNIVERSE_SPEC,
    SourceBackedReaderOrderSpec,
    apply_source_backed_reader_order_migration,
    build_source_backed_reader_order_dry_run,
)
from app.services.ultimate_universe_production_migration import (  # noqa: E402
    MigrationInvariantError,
)

CONFIRMATION = "STEP27-READER-ORDER"
SOURCE_MANIFESTS: dict[str, SourceBackedReaderOrderSpec] = {
    "absolute-universe": PRODUCTION_ABSOLUTE_UNIVERSE_SPEC,
}
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


def _status(report: dict[str, Any]) -> str:
    """Return the Step 27 coordinator classification for one dry-run."""
    if report.get("ok") is True:
        return "clean"
    errors = [str(error) for error in report.get("errors", [])]
    if any("needs_review" in error for error in errors):
        return "blocked-by-needs-review"
    if any(
        phrase in error
        for error in errors
        for phrase in (
            "Roll eligibility would change",
            "loses protection",
            "does not exactly reproduce",
        )
    ):
        return "behavior-mismatch"
    return "blocked-by-identity"


async def _build_report(manifest: str) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        if manifest in SOURCE_MANIFESTS:
            report = await build_source_backed_reader_order_dry_run(
                db,
                SOURCE_MANIFESTS[manifest],
            )
        else:
            report = await build_explicit_reader_order_dry_run(
                db,
                EXPLICIT_MANIFESTS[manifest],
            )
        await db.rollback()
    return report


async def _dry_run(manifest: str, output: Path) -> int:
    report = await _build_report(manifest)
    report = {"status": _status(report), **report}
    _write_json(output, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] is True else 2


async def _batch_dry_run(
    manifests: list[str],
    output_dir: Path,
    summary_path: Path,
) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for manifest in manifests:
        report = await _build_report(manifest)
        status = _status(report)
        payload = {"status": status, **report}
        output = output_dir / f"{manifest}.json"
        _write_json(output, payload)
        rows.append(
            {
                "manifest": manifest,
                "status": status,
                "ok": report.get("ok") is True,
                "errors": report.get("errors", []),
                "snapshot_token": report.get("snapshot_token"),
                "output": str(output),
            }
        )
    summary = {
        "manifests": rows,
        "clean": [row["manifest"] for row in rows if row["status"] == "clean"],
        "blocked": [row["manifest"] for row in rows if row["status"] != "clean"],
    }
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Step 27 reader-order migration")
    subparsers = parser.add_subparsers(dest="command", required=True)

    dry = subparsers.add_parser("dry-run", help="read-only preflight for one manifest")
    dry.add_argument("--manifest", choices=ALL_MANIFESTS, required=True)
    dry.add_argument("--output", type=Path, required=True)

    batch = subparsers.add_parser(
        "batch-dry-run",
        help="read-only preflight for the explicit Step 14 migration batch",
    )
    batch.add_argument(
        "--manifest",
        action="append",
        choices=sorted(EXPLICIT_MANIFESTS),
        dest="manifests",
        help="manifest to include; repeat as needed; defaults to every explicit manifest",
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
    return parser


async def _main() -> int:
    args = _parser().parse_args()
    if args.command == "dry-run":
        return await _dry_run(args.manifest, args.output)
    if args.command == "batch-dry-run":
        manifests = args.manifests or sorted(EXPLICIT_MANIFESTS)
        return await _batch_dry_run(manifests, args.output_dir, args.summary)
    if args.command == "apply":
        return await _apply(
            args.manifest,
            args.snapshot,
            args.receipt,
            args.confirm,
        )
    raise AssertionError(f"unhandled command {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(_main()))
    except MigrationInvariantError as exc:
        print(f"Step 27 migration refused: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

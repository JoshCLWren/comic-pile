#!/usr/bin/env python3
r"""Reviewed operator CLI for reseating misordered ordinary issue threads.

CBL adoption historically appended missing numbers, so prod threads such as
Ultimate X-Men 17982 and Ultimate Spider-Man 17977 can read
``#7–#24, #2–#6, #1``. Roll follows ``Issue.position`` plus explicit
checkpoints, so next-unread then skips the early unread issues.

This script only rewrites ``Issue.position`` for threads whose numbers are
all ordinary positive integers. It does not infer dependencies, does not
create a second ordering system, and does not mutate read history.

Commands:

    uv run python scripts/repair_thread_natural_issue_order.py preflight \\
        --output /tmp/natural-order-preflight.json
    uv run python scripts/repair_thread_natural_issue_order.py apply \\
        --confirm NATURAL-ISSUE-ORDER-REPAIR \\
        --output /tmp/natural-order-apply.json
    uv run python scripts/repair_thread_natural_issue_order.py rollback \\
        --confirm NATURAL-ISSUE-ORDER-REPAIR \\
        --snapshot /tmp/natural-order-apply.json \\
        --output /tmp/natural-order-rollback.json

Preflight is read-only: it rolls the transaction back. Apply and rollback
are transactional and refuse to run without the confirmation token. Apply
writes the durable rollback snapshot before the database commit so a
snapshot-write failure cannot leave an irreversible reseat. This file is
committed for review and must not be executed against production from the
#3483 implementation change.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile

from app.database import AsyncSessionLocal
from app.services.thread_natural_order_repair import (
    CONFIRMATION_TOKEN,
    NaturalOrderRepairError,
    NaturalOrderRepairReport,
    repair_thread_natural_issue_order,
    rollback_thread_natural_issue_order,
)


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    """Write JSON via temp file + fsync + replace so readers never see a partial file.

    Args:
        path: Destination path for the durable snapshot.
        payload: JSON-serializable object.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        # Best-effort directory fsync so the rename itself is durable.
        dir_fd = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise NaturalOrderRepairError(f"expected JSON object in {path}")
    return value


def _require_confirmation(value: str | None) -> None:
    if value != CONFIRMATION_TOKEN:
        raise NaturalOrderRepairError(
            f"mutating command requires --confirm {CONFIRMATION_TOKEN}"
        )


def build_parser() -> argparse.ArgumentParser:
    """Build the operator CLI parser.

    Returns:
        Parser whose subcommand is required so apply cannot be the default.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Reseat ordinary numeric thread issues into natural order. "
            "Preflight is read-only. Apply and rollback require confirmation."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    preflight = subparsers.add_parser(
        "preflight",
        help="read-only scan; rolls the transaction back",
    )
    apply_parser = subparsers.add_parser(
        "apply",
        help="transactionally reseat planned threads",
    )
    rollback = subparsers.add_parser(
        "rollback",
        help="restore positions from an apply snapshot",
    )
    for subparser in (preflight, apply_parser):
        subparser.add_argument("--user-id", type=int, default=None)
        subparser.add_argument("--thread-id", type=int, default=None)
        subparser.add_argument("--limit", type=int, default=None)
        subparser.add_argument("--output", type=Path, required=True)
    apply_parser.add_argument("--confirm")
    rollback.add_argument("--snapshot", type=Path, required=True)
    rollback.add_argument("--output", type=Path, required=True)
    rollback.add_argument("--confirm")
    return parser


def _print_summary(report: NaturalOrderRepairReport) -> None:
    print(
        json.dumps(
            {
                "mode": report.mode,
                "scanned": report.scanned,
                "skipped_irregular": report.skipped_irregular,
                "skipped_already_natural": report.skipped_already_natural,
                "repaired": report.repaired,
                "committed": report.committed,
                "thread_ids": [repair.thread_id for repair in report.repairs],
            },
            indent=2,
            sort_keys=True,
        )
    )


async def _preflight(args: argparse.Namespace) -> int:
    async with AsyncSessionLocal() as db:
        report = await repair_thread_natural_issue_order(
            db,
            user_id=args.user_id,
            thread_id=args.thread_id,
            limit=args.limit,
            commit=False,
            apply_changes=False,
        )
    _write_json_atomic(args.output, report.to_snapshot())
    _print_summary(report)
    return 0


async def _apply(args: argparse.Namespace) -> int:
    """Apply reseats only after the rollback snapshot is durably written.

    The service mutates inside the open transaction with ``commit=False``.
    The snapshot is published atomically next; only then does the DB commit.
    Any snapshot-write failure rolls the transaction back so production cannot
    be left reseated without a rollback artifact.
    """
    _require_confirmation(args.confirm)
    async with AsyncSessionLocal() as db:
        try:
            report = await repair_thread_natural_issue_order(
                db,
                user_id=args.user_id,
                thread_id=args.thread_id,
                limit=args.limit,
                commit=False,
                apply_changes=True,
            )
            # Durable before-state (and after-state) must exist before commit.
            committed_report = NaturalOrderRepairReport(
                mode=report.mode,
                scanned=report.scanned,
                skipped_irregular=report.skipped_irregular,
                skipped_already_natural=report.skipped_already_natural,
                repaired=report.repaired,
                committed=True,
                repairs=report.repairs,
            )
            _write_json_atomic(args.output, committed_report.to_snapshot())
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    _print_summary(committed_report)
    return 0


async def _rollback(args: argparse.Namespace) -> int:
    _require_confirmation(args.confirm)
    snapshot = _read_json(args.snapshot)
    async with AsyncSessionLocal() as db:
        try:
            report = await rollback_thread_natural_issue_order(
                db,
                snapshot,
                commit=False,
                apply_changes=True,
            )
            committed_report = NaturalOrderRepairReport(
                mode=report.mode,
                scanned=report.scanned,
                skipped_irregular=report.skipped_irregular,
                skipped_already_natural=report.skipped_already_natural,
                repaired=report.repaired,
                committed=True,
                repairs=report.repairs,
            )
            _write_json_atomic(args.output, committed_report.to_snapshot())
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    _print_summary(committed_report)
    return 0


async def async_main(argv: list[str] | None = None) -> int:
    """Run one operator command.

    Args:
        argv: Optional argument list; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code.
    """
    args = build_parser().parse_args(argv)
    if args.command == "preflight":
        return await _preflight(args)
    if args.command == "apply":
        return await _apply(args)
    if args.command == "rollback":
        return await _rollback(args)
    raise AssertionError(f"unhandled command {args.command}")


def main(argv: list[str] | None = None) -> int:
    """Entry point that maps repair refusals to exit status 2.

    Args:
        argv: Optional argument list; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code.
    """
    try:
        return asyncio.run(async_main(argv))
    except NaturalOrderRepairError as exc:
        print(f"Natural-order repair refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

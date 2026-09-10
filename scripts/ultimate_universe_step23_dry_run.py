#!/usr/bin/env python3
"""Read-only operator CLI for the Step 23A Ultimate Universe preflight."""

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
from app.services.ultimate_universe_production_migration import (  # noqa: E402
    build_ultimate_universe_dry_run,
)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


async def _run(output: Path) -> int:
    async with AsyncSessionLocal() as db:
        report = await build_ultimate_universe_dry_run(db)
        await db.rollback()
    _write_json(output, report)
    summary = {
        "ok": report["ok"],
        "errors": report["errors"],
        "snapshot_token": report["snapshot_token"],
        "source_position_count": report.get("source", {}).get("position_count"),
        "source_legacy_dependency_count": len(report.get("source_legacy_dependencies", [])),
        "historical_gap_bridge_count": len(report.get("historical_gap_bridges", [])),
        "reused_standalone_rule_count": report.get("planned", {}).get(
            "reused_standalone_rule_count"
        ),
        "current_affected_roll_eligible_thread_ids": report.get(
            "runtime_behavior", {}
        ).get("current_affected_roll_eligible_thread_ids"),
        "simulated_future_eligible_thread_ids": report.get(
            "runtime_behavior", {}
        ).get("simulated_future_eligible_thread_ids"),
        "output": str(output),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if report["ok"] is True else 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Step 23A Ultimate Universe production dry-run"
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


if __name__ == "__main__":
    args = _parser().parse_args()
    raise SystemExit(asyncio.run(_run(args.output)))

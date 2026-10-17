#!/usr/bin/env python3
"""Rotate the live, proven-free OpenCode catalog over durable factory identities."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from factory_model_catalog import parse_opencode_models_text
from factory_roster import load_roster_rows, opencode_model_is_free


def free_models(raw_catalog: str) -> list[str]:
    """Cost metadata wins over names: never silently select a paid model."""
    catalog = parse_opencode_models_text(raw_catalog, "opencode")
    return sorted(
        entry.model_id
        for entry in catalog.entries
        if not entry.cost_is_paid
        and (entry.cost_is_zero or opencode_model_is_free(entry.model_id))
    )


def select_model(
    raw_catalog: str,
    worker: int,
    rotation: int,
    roster_path: Path,
) -> dict[str, str | int]:
    """Rotate all free models without assigning duplicate permanent pins."""
    models = free_models(raw_catalog)
    if not models:
        raise ValueError("OpenCode catalog has no provably free models")
    rows = load_roster_rows(roster_path)
    workers = sorted(
        int(row["worker"]) for row in rows if row["source"] == "opencode-free"
    )
    if worker not in workers:
        raise ValueError(f"worker {worker} has no OpenCode free slot")
    model = models[(workers.index(worker) + rotation) % len(models)]
    return {
        "model": model,
        "runtime_model": f"opencode/{model}",
        "provider": "opencode-free",
        "candidate_count": len(models),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--worker", type=int, required=True)
    parser.add_argument("--rotation", type=int, required=True)
    parser.add_argument("--roster", type=Path, default=Path(".github/free-model-factories.tsv"))
    args = parser.parse_args()
    selected = select_model(
        args.catalog.read_text(encoding="utf-8"),
        args.worker,
        args.rotation,
        args.roster,
    )
    print(json.dumps(selected, sort_keys=True))


if __name__ == "__main__":
    main()

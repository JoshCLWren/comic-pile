#!/usr/bin/env python3
"""Choose a Kilo CLI model from its live 'kilo models' output."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


def discover_models(catalog_text: str) -> list[str]:
    """Preserve published Kilo selectors; never manufacture a model name."""
    ansi = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
    found: set[str] = set()
    for raw in catalog_text.splitlines():
        selector = ansi.sub("", raw).strip()
        if "/" not in selector or any(char.isspace() for char in selector):
            continue
        provider, model = selector.split("/", 1)
        if not provider or not model:
            continue
        found.add(selector)
    return sorted(found)


def choose(
    catalog_text: str, worker: str, excluded: set[str] | None = None,
) -> dict[str, str]:
    candidates = [
        item for item in discover_models(catalog_text) if item not in (excluded or set())
    ]
    if not candidates:
        raise ValueError("Kilo CLI reported no eligible catalog candidates")
    offset = int.from_bytes(hashlib.sha256(worker.encode()).digest()[:8], "big")
    selected = candidates[offset % len(candidates)]
    return {"model": selected, "runtime_model": selected, "source": "kilo-auto",
            "reason": "selected-from-live-kilo-cli"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--worker", required=True)
    parser.add_argument("--exclusions-file", type=Path)
    args = parser.parse_args()
    try:
        excluded: set[str] = set()
        if args.exclusions_file:
            data = json.loads(args.exclusions_file.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("kilo-auto", []), list):
                raise ValueError("invalid model exclusion projection")
            excluded = set(data.get("kilo-auto", []))
        result = choose(args.catalog.read_text(encoding="utf-8"), args.worker, excluded)
    except (OSError, ValueError) as exc:
        print(f"Kilo catalog: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

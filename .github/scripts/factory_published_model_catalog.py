#!/usr/bin/env python3
"""Resolve executable model IDs from a provider-published catalog, not TSV hints.

No inference is used for discovery. Unknown pricing, a failed catalog read, or
absence of an eligible free model never authorizes paid fallback.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

# The following sources publish authoritative zero-price model metadata.
# Other sources require a provider-specific free-tier contract before being
# switched to catalog selection. Never infer "free" from a model's name.
PUBLIC_CATALOGS: dict[str, str] = {
    "openrouter-free": "https://openrouter.ai/api/v1/models",
    "vercel-ai-gateway": "https://ai-gateway.vercel.sh/v1/models",
}


class CatalogUnavailableError(RuntimeError):
    """A provider catalog cannot prove an eligible route."""


def _zero(raw: Any) -> bool:
    try:
        return raw is not None and Decimal(str(raw)) == 0
    except (InvalidOperation, ValueError, TypeError):
        return False


def _free(source: str, item: Mapping[str, Any]) -> bool:
    model = item.get("id")
    if not isinstance(model, str) or not model or any(ch.isspace() for ch in model):
        return False
    pricing = item.get("pricing")
    if not isinstance(pricing, Mapping):
        return False
    if source == "openrouter-free":
        return (
            model.endswith(":free")
            and _zero(pricing.get("prompt"))
            and _zero(pricing.get("completion"))
        )
    if source == "vercel-ai-gateway":
        return _zero(pricing.get("input")) and _zero(pricing.get("output"))
    return False


def free_model_ids(source: str, catalog: Mapping[str, Any]) -> list[str]:
    if source not in PUBLIC_CATALOGS:
        raise ValueError(f"source does not expose verified zero-price catalog: {source}")
    rows = catalog.get("data")
    if not isinstance(rows, list):
        raise CatalogUnavailableError("published model catalog has no data list")
    return sorted({
        row["id"]
        for row in rows
        if isinstance(row, Mapping) and _free(source, row)
    })


def choose_model(
    source: str, worker: str, catalog: Mapping[str, Any],
    exclusions: set[str] | None = None,
) -> str:
    if not worker.isdecimal():
        raise ValueError("worker must be a numeric slot ID")
    candidates = [
        model for model in free_model_ids(source, catalog)
        if model not in (exclusions or set())
    ]
    if not candidates:
        raise CatalogUnavailableError(f"{source}: no verified zero-price models available")
    # Deterministic across runs, independent of manually curated roster pins.
    seed = hashlib.sha256(f"{source}:{worker}".encode()).digest()
    return candidates[int.from_bytes(seed[:8], "big") % len(candidates)]


def published_catalog(source: str, *, timeout: float = 20) -> dict[str, Any]:
    url = PUBLIC_CATALOGS.get(source)
    if url is None:
        raise ValueError(f"no published free catalog contract for {source}")
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "ComicPile-factory-catalog/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise CatalogUnavailableError(f"{source}: model catalog HTTP {response.status}")
            raw = response.read(5_000_001)
    except (OSError, urllib.error.URLError) as exc:
        raise CatalogUnavailableError(f"{source}: model catalog unavailable") from exc
    if len(raw) > 5_000_000:
        raise CatalogUnavailableError(f"{source}: model catalog exceeded size limit")
    try:
        catalog = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise CatalogUnavailableError(f"{source}: invalid published catalog JSON") from exc
    if not isinstance(catalog, dict):
        raise CatalogUnavailableError(f"{source}: catalog must be a JSON object")
    return catalog


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, choices=sorted(PUBLIC_CATALOGS))
    parser.add_argument("--worker", required=True)
    parser.add_argument("--catalog-json", type=Path, help="offline fixture for tests only")
    parser.add_argument("--exclusions-file", type=Path)
    args = parser.parse_args(argv)
    try:
        catalog = (
            json.loads(args.catalog_json.read_text(encoding="utf-8"))
            if args.catalog_json else published_catalog(args.source)
        )
        if not isinstance(catalog, dict):
            raise CatalogUnavailableError("catalog must be an object")
        excluded: set[str] = set()
        if args.exclusions_file and args.exclusions_file.is_file():
            raw = json.loads(args.exclusions_file.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise CatalogUnavailableError("Neon model exclusions are invalid")
            models = raw.get(args.source, [])
            if not isinstance(models, list) or not all(isinstance(x, str) for x in models):
                raise CatalogUnavailableError("Neon model exclusions are invalid")
            excluded = set(models)
        model = choose_model(args.source, args.worker, catalog, excluded)
    except (CatalogUnavailableError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"factory catalog: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"source": args.source, "model": model, "catalog_verified": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Select another *discovered* model for the same leased factory provider.

This is called by the trusted worker after a real inference failure. Attempted
models are excluded for the rest of that lease, regardless of their cooldown.
No roster, guessed model ID, or cross-provider fallback is involved.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping


class ExhaustedCandidates(ValueError):
    """The provider has no eligible model that has not been attempted."""


def select_next(
    source: str,
    worker: str,
    attempted: set[str],
    exclusions: Mapping[str, list[str]],
    *,
    catalog_text: str | None = None,
    catalog_json: Mapping[str, Any] | None = None,
    rotation: int = 0,
) -> dict[str, Any]:
    """Discover and choose an unattempted exact model on this provider."""
    excluded = set(exclusions.get(source, ())) | attempted
    if source == "opencode-free":
        from factory_live_opencode import catalog_models, select_model

        if catalog_text is None:
            raise ValueError("trusted OpenCode catalog snapshot missing")
        if not (set(catalog_models(catalog_text, provider=source)) - excluded):
            raise ExhaustedCandidates("no eligible unattempted OpenCode models")
        return select_model(
            catalog_text, int(worker), rotation,
            attempted=excluded, provider=source,
        )
    if source == "kilo-auto":
        from factory_kilo_catalog import choose, discover_models

        if catalog_text is None:
            raise ValueError("trusted Kilo catalog snapshot missing")
        if not (set(discover_models(catalog_text)) - excluded):
            raise ExhaustedCandidates("no eligible unattempted Kilo models")
        return choose(catalog_text, worker, excluded)
    if source == "openrouter-free":
        from factory_published_model_catalog import (
            catalog_model_ids,
            choose_model,
            published_catalog,
        )

        catalog = catalog_json if catalog_json is not None else published_catalog(source)
        if not (set(catalog_model_ids(source, catalog)) - excluded):
            raise ExhaustedCandidates("no eligible unattempted OpenRouter free models")
        model = choose_model(source, worker, catalog, excluded)
        return {"source": source, "model": model, "runtime_model": f"openrouter/{model}"}

    from factory_provider_candidates import discover
    from factory_runtime_model_select import provider_catalog, select

    catalog = catalog_json if catalog_json is not None else provider_catalog(source, os.environ)
    if not any(candidate.model not in excluded
               for candidate in discover(source, json.dumps(catalog)).candidates):
        raise ExhaustedCandidates(f"no eligible unattempted {source} models")
    return select(source, worker, catalog, {source: sorted(excluded)})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--worker", required=True)
    parser.add_argument("--exclusions-file", type=Path, required=True)
    parser.add_argument("--catalog-file", type=Path)
    parser.add_argument("--catalog-json", type=Path, help="offline catalog fixture")
    parser.add_argument("--attempted", action="append", default=[])
    parser.add_argument("--rotation", type=int, default=0)
    args = parser.parse_args()
    try:
        if not args.worker.isdecimal() or int(args.worker) < 1:
            raise ValueError("invalid worker identity")
        exclusions = json.loads(args.exclusions_file.read_text(encoding="utf-8"))
        if not isinstance(exclusions, dict) or any(
            not isinstance(models, list) or not all(isinstance(x, str) for x in models)
            for models in exclusions.values()
        ):
            raise ValueError("invalid trusted model exclusion projection")
        catalog_text = (
            args.catalog_file.read_text(encoding="utf-8") if args.catalog_file else None
        )
        catalog_json = (
            json.loads(args.catalog_json.read_text(encoding="utf-8"))
            if args.catalog_json else None
        )
        selected = select_next(
            args.source, args.worker, set(args.attempted), exclusions,
            catalog_text=catalog_text, catalog_json=catalog_json,
            rotation=args.rotation,
        )
    except ExhaustedCandidates as exc:
        print(f"factory failover exhausted: {exc}", file=sys.stderr)
        return 3
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(f"factory failover error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(selected, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

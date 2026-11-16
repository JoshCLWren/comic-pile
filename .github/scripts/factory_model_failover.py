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
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
import shutil
import subprocess


class ExhaustedCandidatesError(ValueError):
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
            raise ExhaustedCandidatesError("no eligible unattempted OpenCode models")
        return select_model(
            catalog_text, int(worker), rotation,
            attempted=excluded, provider=source,
        )
    if source == "kilo-auto":
        from factory_kilo_catalog import choose, discover_models

        if catalog_text is None:
            raise ValueError("trusted Kilo catalog snapshot missing")
        if not (set(discover_models(catalog_text)) - excluded):
            raise ExhaustedCandidatesError("no eligible unattempted Kilo models")
        return choose(catalog_text, worker, excluded)
    if source == "openrouter-free":
        from factory_published_model_catalog import (
            catalog_model_ids,
            choose_model,
            published_catalog,
        )

        catalog = catalog_json if catalog_json is not None else published_catalog(source)
        if not (set(catalog_model_ids(source, catalog)) - excluded):
            raise ExhaustedCandidatesError("no eligible unattempted OpenRouter free models")
        model = choose_model(source, worker, catalog, excluded)
        return {"source": source, "model": model, "runtime_model": f"openrouter/{model}"}

    from factory_provider_candidates import discover
    from factory_runtime_model_select import provider_catalog, select

    catalog = catalog_json if catalog_json is not None else provider_catalog(source, os.environ)
    if not any(candidate.model not in excluded
               for candidate in discover(source, json.dumps(catalog)).candidates):
        raise ExhaustedCandidatesError(f"no eligible unattempted {source} models")
    return select(source, worker, catalog, {source: sorted(excluded)})



def select_next_fleet(
    worker: str,
    original_source: str,
    attempted: set[tuple[str, str]],
    blocked_providers: set[str],
    exclusions: Mapping[str, list[str]],
    catalogs: Mapping[str, Mapping[str, Any] | str],
    eligible_sources: set[str],
    *,
    rotation: int = 0,
) -> dict[str, Any]:
    """Select the next provider/model from canonical catalogs, not one source.

    A provider/account breaker skips every model at that source; model-only
    failures exclude precisely one canonical pair. The eligible_sources set
    is the trusted controller's admission projection, not a model roster.
    """
    sources = sorted(eligible_sources & set(catalogs) - blocked_providers)
    if original_source in sources:
        sources.remove(original_source)
        sources.insert(0, original_source)
    for source in sources:
        catalog = catalogs[source]
        excluded = {model for provider, model in attempted if provider == source}
        try:
            candidate = select_next(
                source, worker, excluded, exclusions,
                catalog_text=catalog if isinstance(catalog, str) else None,
                catalog_json=catalog if isinstance(catalog, Mapping) else None,
                rotation=rotation,
            )
        except ExhaustedCandidatesError:
            continue
        if (candidate["source"], candidate["model"]) in attempted:
            raise ValueError("selector returned an attempted canonical pair")
        return candidate
    raise ExhaustedCandidatesError("no eligible provider/model combination remains")



def discover_fleet_catalogs(
    eligible_sources: set[str],
    *,
    cache: Path,
    env: Mapping[str, str],
    existing_catalogs: Mapping[str, Path] | None = None,
) -> dict[str, Any]:
    """Take one canonical snapshot per assignment; never probe model inference.

    Catalog endpoints may fail independently. Missing credentials skip only
    that provider, not its neighbors. Failed catalog reads are not attributed
    to any model's health or quota.
    """
    from factory_provider_registry import PROVIDERS, missing_credentials
    from factory_runtime_model_select import provider_catalog

    if cache.is_file():
        saved = json.loads(cache.read_text(encoding="utf-8"))
        if not isinstance(saved, dict):
            raise ValueError("invalid trusted fleet catalog snapshot")
        return saved

    files = existing_catalogs or {}
    def fetch(source: str) -> tuple[str, Any]:
        if source in files and files[source].is_file():
            return source, files[source].read_text(encoding="utf-8")
        if source == "opencode-free":
            if not shutil.which("opencode"):
                raise ValueError("OpenCode CLI missing")
            run = subprocess.run(
                ["opencode", "models", "opencode", "--refresh"],
                check=True, capture_output=True, text=True, timeout=35,
            )
            return source, run.stdout
        if source == "kilo-auto":
            if not shutil.which("kilo"):
                raise ValueError("Kilo CLI missing")
            run = subprocess.run(
                ["kilo", "models", "kilo-auto", "--refresh"],
                check=True, capture_output=True, text=True, timeout=35,
            )
            return source, run.stdout
        if source == "openrouter-free":
            if not env.get("OPENROUTER_API_KEY"):
                raise ValueError("OpenRouter credentials missing")
            from factory_published_model_catalog import published_catalog
            return source, published_catalog(source)
        spec = PROVIDERS.get(source)
        if spec is None or missing_credentials(spec, env):
            raise ValueError("provider credentials or canonical integration missing")
        if source == "vercel-ai-gateway":
            from factory_published_model_catalog import published_catalog
            return source, published_catalog(source)
        return source, provider_catalog(source, env)

    discovered: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=min(6, max(1, len(eligible_sources)))) as executor:
        pending = {executor.submit(fetch, s): s for s in sorted(eligible_sources)}
        for future in as_completed(pending):
            try:
                source, catalog = future.result()
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                continue
            discovered[source] = catalog
    cache.write_text(json.dumps(discovered, sort_keys=True), encoding="utf-8")
    return discovered


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--eligible-sources-file", type=Path)
    parser.add_argument("--fleet-catalog-cache", type=Path)
    parser.add_argument("--attempted-pair", action="append", default=[])
    parser.add_argument("--blocked-provider", action="append", default=[])
    parser.add_argument("--worker", required=True)
    parser.add_argument("--exclusions-file", type=Path, required=True)
    parser.add_argument("--catalog-file", type=Path)
    parser.add_argument("--catalog-json", type=Path, help="offline catalog fixture")
    parser.add_argument("--catalog-cache", type=Path, help="trusted per-run catalog snapshot")
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
        # Fetch once per assignment. Each failed model then advances through the
        # same authoritative published snapshot without hammering the provider.
        if catalog_json is None and args.catalog_cache and args.catalog_cache.is_file():
            catalog_json = json.loads(args.catalog_cache.read_text(encoding="utf-8"))
        if (catalog_json is None and args.catalog_cache
                and args.source not in {"opencode-free", "kilo-auto"}):
            if args.source == "openrouter-free":
                from factory_published_model_catalog import published_catalog
                catalog_json = published_catalog(args.source)
            else:
                from factory_runtime_model_select import provider_catalog
                catalog_json = provider_catalog(args.source, os.environ)
            args.catalog_cache.write_text(json.dumps(catalog_json), encoding="utf-8")
        if args.eligible_sources_file is None:
            selected = select_next(
                args.source, args.worker, set(args.attempted), exclusions,
                catalog_text=catalog_text, catalog_json=catalog_json,
                rotation=args.rotation,
            )
        else:
            sources = json.loads(args.eligible_sources_file.read_text(encoding="utf-8"))
            if not isinstance(sources, list) or not all(isinstance(s, str) for s in sources):
                raise ValueError("invalid trusted fleet capacity projection")
            if args.fleet_catalog_cache is None:
                raise ValueError("fleet catalog cache missing")
            files = {args.source: args.catalog_file} if args.catalog_file else {}
            catalogs = discover_fleet_catalogs(
                set(sources), cache=args.fleet_catalog_cache,
                env=os.environ, existing_catalogs=files,
            )
            pairs: set[tuple[str, str]] = set()
            for raw in args.attempted_pair:
                pair = json.loads(raw)
                if not isinstance(pair, list) or len(pair) != 2 or not all(
                    isinstance(s, str) for s in pair
                ):
                    raise ValueError("invalid attempted provider/model pair")
                pairs.add((pair[0], pair[1]))
            selected = select_next_fleet(
                args.worker, args.source, pairs, set(args.blocked_provider),
                exclusions, catalogs, set(sources), rotation=args.rotation,
            )
    except ExhaustedCandidatesError as exc:
        print(f"factory failover exhausted: {exc}", file=sys.stderr)
        return 3
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(f"factory failover error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(selected, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

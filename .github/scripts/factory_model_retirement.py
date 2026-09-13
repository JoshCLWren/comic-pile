#!/usr/bin/env python3
"""Discover live OpenCode catalogs and retire dead factory roster pins.

The scheduled workflow opens a PR that only removes catalog-absent pins.
Unused free OpenCode models are reported, not auto-added. Paid Zen models
are never proposed for ``opencode-free`` lanes. NVIDIA pins are judged only
by ``opencode models nvidia``, never by integrate.api.nvidia.com.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from factory_model_catalog import (
    FACTORY_PROVIDERS,
    CatalogEntry,
    CatalogUnavailableError,
    ProviderCatalog,
    load_provider_catalogs,
    strip_provider_prefix,
)
from factory_roster import (
    PROTECTED_SOURCES,
    RosterLock,
    RosterRow,
    default_lock_path,
    default_roster_path,
    load_roster_comments,
    load_roster_lock,
    load_roster_rows,
    opencode_model_is_free,
    openrouter_model_is_free,
    sync_roster_lock,
    write_roster_rows,
)


PROVIDER_BY_SOURCE = {
    "opencode-free": "opencode",
    "nvidia": "nvidia",
    "openrouter-free": "openrouter",
}


@dataclass(frozen=True)
class PinDecision:
    """Keep-or-retire decision for one roster pin."""

    worker: str
    source: str
    model: str
    action: str
    reason: str


@dataclass(frozen=True)
class UnusedFreeModel:
    """A live free OpenCode model that is not currently pinned."""

    provider: str
    model: str
    cost_input: str | None
    cost_output: str | None
    reason: str


@dataclass(frozen=True)
class RetirementPlan:
    """Diff between the factory roster and live OpenCode catalogs."""

    retirements: tuple[PinDecision, ...]
    kept: tuple[PinDecision, ...]
    unused_free: tuple[UnusedFreeModel, ...]
    paid_rejected: tuple[str, ...]
    catalog_sources: dict[str, str]

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serializable report."""
        return {
            "retirements": [asdict(item) for item in self.retirements],
            "kept": [asdict(item) for item in self.kept],
            "unused_free": [asdict(item) for item in self.unused_free],
            "paid_rejected": list(self.paid_rejected),
            "catalog_sources": dict(self.catalog_sources),
        }


def classify_opencode_free_eligibility(
    model: str,
    entry: CatalogEntry | None,
) -> bool:
    """Return whether a model may occupy an opencode-free factory lane.

    Name rules match ``validate-free-model-factories.py``. Explicit cost==0
    from a verbose catalog also qualifies. A proven paid cost always loses.

    Args:
        model: Bare OpenCode model id.
        entry: Optional verbose catalog row.

    Returns:
        True when the model is eligible for an opencode-free pin.
    """
    if entry is not None and entry.cost_is_paid:
        return False
    if opencode_model_is_free(model):
        return True
    return bool(entry is not None and entry.cost_is_zero)


def _catalog_for_source(
    source: str,
    catalogs: Mapping[str, ProviderCatalog],
) -> ProviderCatalog | None:
    """Return the OpenCode provider catalog that owns a roster source."""
    provider = PROVIDER_BY_SOURCE.get(source)
    if provider is None:
        return None
    return catalogs.get(provider)


def decide_pin(
    row: RosterRow,
    catalogs: Mapping[str, ProviderCatalog],
    retired_models: set[str],
) -> PinDecision:
    """Classify one roster pin against live catalogs and the retirement lock.

    Args:
        row: Factory TSV row.
        catalogs: Loaded OpenCode provider catalogs.
        retired_models: Permanently retired model ids.

    Returns:
        Keep or retire decision.
    """
    worker = row["worker"]
    source = row["source"]
    model = row["model"]
    if model in retired_models:
        return PinDecision(
            worker=worker,
            source=source,
            model=model,
            action="retire",
            reason="permanently retired",
        )
    if source in PROTECTED_SOURCES:
        return PinDecision(
            worker=worker,
            source=source,
            model=model,
            action="keep",
            reason="kilo-auto is not enumerated by OpenCode CLI",
        )
    catalog = _catalog_for_source(source, catalogs)
    if catalog is None:
        return PinDecision(
            worker=worker,
            source=source,
            model=model,
            action="keep",
            reason=f"no {source} OpenCode catalog was loaded; refusing to retire",
        )
    entry = catalog.get(model)
    if entry is None:
        return PinDecision(
            worker=worker,
            source=source,
            model=model,
            action="retire",
            reason=f"absent from opencode models {catalog.provider}",
        )
    if source == "opencode-free" and not classify_opencode_free_eligibility(model, entry):
        return PinDecision(
            worker=worker,
            source=source,
            model=model,
            action="retire",
            reason="present but not opencode-free eligible (paid or non-free id)",
        )
    if source == "openrouter-free" and not openrouter_model_is_free(model):
        return PinDecision(
            worker=worker,
            source=source,
            model=model,
            action="retire",
            reason="openrouter-free pin left the free tier",
        )
    return PinDecision(
        worker=worker,
        source=source,
        model=model,
        action="keep",
        reason=f"present in opencode models {catalog.provider}",
    )


def unused_free_opencode_models(
    catalog: ProviderCatalog | None,
    roster_models: set[str],
) -> tuple[tuple[UnusedFreeModel, ...], tuple[str, ...]]:
    """List live free OpenCode models that are not currently pinned.

    Args:
        catalog: OpenCode provider catalog.
        roster_models: Bare opencode-free pins already on the roster.

    Returns:
        Unused free candidates and paid ids rejected from the proposal list.
    """
    if catalog is None:
        return (), ()
    unused: list[UnusedFreeModel] = []
    paid: list[str] = []
    for entry in catalog.entries:
        if entry.model_id in roster_models:
            continue
        if entry.cost_is_paid:
            paid.append(entry.model_id)
            continue
        if not classify_opencode_free_eligibility(entry.model_id, entry):
            if entry.cost_is_zero is False:
                paid.append(entry.model_id)
            continue
        unused.append(
            UnusedFreeModel(
                provider="opencode",
                model=entry.model_id,
                cost_input=None if entry.cost_input is None else str(entry.cost_input),
                cost_output=None if entry.cost_output is None else str(entry.cost_output),
                reason=(
                    "cost==0"
                    if entry.cost_is_zero
                    else "free-roster name rule"
                ),
            )
        )
    return tuple(unused), tuple(paid)


def plan_retirement(
    rows: Sequence[RosterRow],
    catalogs: Mapping[str, ProviderCatalog],
    *,
    lock: RosterLock | None = None,
) -> RetirementPlan:
    """Diff roster pins against OpenCode catalogs.

    Args:
        rows: Current factory roster.
        catalogs: Live or fixture catalogs.
        lock: Optional retirement lock for permanent retirements.

    Returns:
        Retirement plan and unused-free discovery report.
    """
    retired_models = set(lock["retired_models"]) if lock is not None else set()
    decisions = [decide_pin(row, catalogs, retired_models) for row in rows]
    roster_free = {
        strip_provider_prefix(row["model"], "opencode")
        for row in rows
        if row["source"] == "opencode-free"
    }
    unused, paid = unused_free_opencode_models(catalogs.get("opencode"), roster_free)
    return RetirementPlan(
        retirements=tuple(item for item in decisions if item.action == "retire"),
        kept=tuple(item for item in decisions if item.action == "keep"),
        unused_free=unused,
        paid_rejected=paid,
        catalog_sources={
            provider: catalog.source for provider, catalog in catalogs.items()
        },
    )


def apply_plan(
    rows: Sequence[RosterRow],
    plan: RetirementPlan,
) -> list[RosterRow]:
    """Return roster rows with retired pins removed."""
    retired_workers = {item.worker for item in plan.retirements}
    return [row for row in rows if row["worker"] not in retired_workers]


def required_providers(rows: Sequence[RosterRow]) -> tuple[str, ...]:
    """Return OpenCode providers that must be present before retiring pins."""
    needed: list[str] = []
    for source, provider in PROVIDER_BY_SOURCE.items():
        if any(row["source"] == source for row in rows) and provider not in needed:
            needed.append(provider)
    return tuple(needed)


def assert_catalogs_ready(
    rows: Sequence[RosterRow],
    catalogs: Mapping[str, ProviderCatalog],
) -> None:
    """Fail closed when a roster source has no OpenCode catalog.

    Args:
        rows: Current roster.
        catalogs: Loaded catalogs.

    Raises:
        CatalogUnavailableError: When a required provider catalog is missing.
    """
    missing = [
        provider
        for provider in required_providers(rows)
        if provider not in catalogs
    ]
    if missing:
        raise CatalogUnavailableError(
            "missing OpenCode catalog for: " + ", ".join(missing)
        )


def write_github_output(path: Path, plan: RetirementPlan) -> None:
    """Write workflow ``GITHUB_OUTPUT`` keys for the discovery job."""
    lines = [
        f"retire={'true' if plan.retirements else 'false'}",
        f"retirement_count={len(plan.retirements)}",
        f"unused_free_count={len(plan.unused_free)}",
        f"paid_rejected_count={len(plan.paid_rejected)}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    """Return the retirement CLI parser."""
    parser = argparse.ArgumentParser(
        description="Discover OpenCode catalogs and retire dead factory pins.",
    )
    parser.add_argument("command", choices=("plan", "apply", "discover"))
    parser.add_argument("--catalog-json", type=Path)
    parser.add_argument("--opencode-text", type=Path)
    parser.add_argument("--nvidia-text", type=Path)
    parser.add_argument("--openrouter-text", type=Path)
    parser.add_argument("--roster", type=Path)
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--opencode-bin", default="")
    parser.add_argument(
        "--require-cli",
        action="store_true",
        help="Call live opencode models when a fixture/text dump is missing.",
    )
    parser.add_argument(
        "--fail-on-retirement",
        action="store_true",
        help="Exit 1 when dead pins exist (CI fail-closed without applying).",
    )
    return parser


def _text_paths(args: argparse.Namespace) -> dict[str, Path]:
    """Collect optional per-provider CLI stdout dumps."""
    paths: dict[str, Path] = {}
    if args.opencode_text is not None:
        paths["opencode"] = args.opencode_text
    if args.nvidia_text is not None:
        paths["nvidia"] = args.nvidia_text
    if args.openrouter_text is not None:
        paths["openrouter"] = args.openrouter_text
    return paths


def run(argv: Sequence[str] | None = None) -> int:
    """Run the discovery/retirement CLI.

    Args:
        argv: Optional argument vector.

    Returns:
        Process exit status.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    roster_path = args.roster or default_roster_path()
    lock_path = args.lock or default_lock_path()
    rows = load_roster_rows(roster_path)
    lock = load_roster_lock(lock_path if lock_path.is_file() else None)
    require_cli = bool(args.require_cli) or (
        args.catalog_json is None and not _text_paths(args)
    )
    try:
        catalogs = load_provider_catalogs(
            fixture_path=args.catalog_json,
            text_paths=_text_paths(args),
            providers=required_providers(rows) or FACTORY_PROVIDERS,
            require_cli=require_cli,
            opencode_bin=args.opencode_bin or None,
        )
        assert_catalogs_ready(rows, catalogs)
    except CatalogUnavailableError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    plan = plan_retirement(rows, catalogs, lock=lock)
    report = json.dumps(plan.as_dict(), indent=2, sort_keys=True)
    if args.report is not None:
        args.report.write_text(report + "\n", encoding="utf-8")
    else:
        print(report)
    if args.github_output is not None:
        write_github_output(args.github_output, plan)

    if args.command == "apply" and plan.retirements:
        remaining = apply_plan(rows, plan)
        write_roster_rows(roster_path, remaining, load_roster_comments(roster_path))
        sync_roster_lock(
            remaining,
            lock_path=lock_path,
            extra_retired_workers=(int(item.worker) for item in plan.retirements),
            extra_retired_models=(item.model for item in plan.retirements),
        )
        print(
            f"Retired {len(plan.retirements)} pin(s); "
            f"{len(remaining)} roster slot(s) remain.",
            file=sys.stderr,
        )

    if args.fail_on_retirement and plan.retirements:
        return 1
    return 0


def main() -> int:
    """CLI entry point."""
    return run()


if __name__ == "__main__":
    raise SystemExit(main())

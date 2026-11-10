#!/usr/bin/env python3
"""Rotate the live, proven-free OpenCode catalog over durable factory identities."""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from factory_candidate_health import (
    HEALTHY_OUTCOMES,
    OUTCOME_RE,
    RETIREMENT_MARKER,
    UPDATED_RE,
    flatten_comments,
    latest_attempt_evidence,
)
from factory_completion_controller import parse_time
from factory_model_catalog import parse_opencode_models_text
from factory_roster import load_roster_lock, load_roster_rows, opencode_model_is_free

COOLDOWN_SECONDS = 6 * 60 * 60
MODEL_UNAVAILABLE_RE = re.compile(
    r"Error:\s*Model unavailable:\s*(?P<model>\S+)",
    re.IGNORECASE,
)
RUN_RE = re.compile(r"(?m)^Run: ([0-9]+)$")
FREE_QUOTA_RE = re.compile(r"Free usage limit reached|FreeUsageLimitError", re.IGNORECASE)


def free_models(raw_catalog: str, *, provider: str = "opencode-free") -> list[str]:
    """Enumerate only zero-price candidates from the selected OpenCode provider."""
    if provider not in {"opencode-free", "openrouter-free"}:
        raise ValueError("unsupported free model provider")
    catalog = parse_opencode_models_text(raw_catalog, provider.removesuffix("-free"))
    retired = set(load_roster_lock()["retired_models"])
    return sorted(
        entry.model_id
        for entry in catalog.entries
        if entry.model_id not in retired
        and not entry.cost_is_paid
        and (
            entry.cost_is_zero
            or (
                provider == "opencode-free"
                and opencode_model_is_free(entry.model_id)
            )
            or (provider == "openrouter-free" and entry.model_id.endswith(":free"))
        )
    )


def unavailable_models(
    payload: object, *, now_epoch: int, provider: str = "opencode-free"
) -> set[str]:
    """Return model-specific exclusions from trusted, timestamped registry records."""
    comments = []
    for comment in flatten_comments(payload):
        body = str(comment.get("body") or "")
        if RUN_RE.search(body) is None:
            continue
        if not any(
            marker in body
            for marker in (
                "<!-- factory-attempt-outcome:v1 ",
                "<!-- factory-model-unavailable:v1 ",
                "<!-- factory-provider-quota:v1 ",
                "<!-- factory-model-retired-410:v1 -->",
            )
        ):
            continue
        timestamp = UPDATED_RE.search(body)
        updated = parse_time(timestamp.group("updated")) if timestamp else None
        if updated is None or updated > now_epoch:
            continue
        # Generic/provider/control-plane failures do not prove model recovery.
        # Do not let their newer worker summary hide durable unavailability.
        outcome = OUTCOME_RE.search(body)
        if RETIREMENT_MARKER not in body and (
            outcome is None
            or outcome.group("outcome")
            not in HEALTHY_OUTCOMES | {"model_unavailable", "model_retired_410", "provider_quota"}
        ):
            continue
        comments.append(comment)
    excluded = set()
    for evidence in latest_attempt_evidence(comments).values():
        if evidence.provider != provider or evidence.updated > now_epoch:
            continue
        if evidence.outcome == "model_retired_410" or (
            evidence.outcome in {"model_unavailable", "provider_quota"}
            and now_epoch < evidence.updated + COOLDOWN_SECONDS
        ):
            excluded.add(evidence.model.removeprefix(provider.removesuffix("-free") + "/"))
    return excluded


def record_smoke_failure(log_content: str, runtime_model: str, outcome_file: Path) -> bool:
    """Persist recognizable OpenCode smoke errors for the registry reporter."""
    if runtime_model.startswith(("mistral/", "ollama-cloud/")) and re.search(
        r"budget[ _]exhausted|billing_api_budget_exhausted|monthly usage limit|"
        r"reached your [a-z ]*usage limit", log_content, re.I,
    ):
        outcome_file.write_text(
            f"provider_quota\tMonthly free provider quota exhausted for {runtime_model}\n",
            encoding="utf-8",
        )
        return True
    if runtime_model.startswith(("z-ai/", "kilo/")) and re.search(
        r"(?<![0-9.])429(?!\d)|too many requests", log_content, re.I
    ):
        outcome_file.write_text(
            f"provider_quota\tFree provider account rate limit for {runtime_model}\n",
            encoding="utf-8",
        )
        return True
    if runtime_model.startswith(("opencode/", "openrouter/")) and FREE_QUOTA_RE.search(log_content):
        outcome_file.write_text(
            f"provider_quota\tFree account quota exhausted for {runtime_model}\n",
            encoding="utf-8",
        )
        return True
    if not any(
        match.group("model") == runtime_model
        for match in MODEL_UNAVAILABLE_RE.finditer(log_content)
    ):
        return False
    outcome_file.write_text(
        f"model_unavailable\tModel unavailable: {runtime_model}\n",
        encoding="utf-8",
    )
    return True


def select_model(
    raw_catalog: str,
    worker: int,
    rotation: int,
    roster_path: Path,
    comments_path: Path | None = None,
    *,
    now_epoch: int | None = None,
    attempted: set[str] | None = None,
    provider: str = "opencode-free",
) -> dict[str, str | int]:
    """Rotate all free models without assigning duplicate permanent pins.

    Consults trusted registry attempt comments and applies model cooldowns.
    """
    models = free_models(raw_catalog, provider=provider)
    if not models:
        raise ValueError("OpenCode catalog has no provably free models")

    excluded = set()
    if comments_path is not None:
        # Evidence read/JSON errors must fail closed rather than silently forget cooldowns.
        payload = json.loads(comments_path.read_text(encoding="utf-8"))
        excluded = unavailable_models(
            payload,
            now_epoch=int(time.time()) if now_epoch is None else now_epoch,
            provider=provider,
        )
    available_models = [model for model in models if model not in excluded and model not in (attempted or set())]
    if not available_models:
        raise ValueError(f"All {len(models)} candidates are unavailable or in cooldown")

    rows = load_roster_rows(roster_path)
    workers = sorted(int(row["worker"]) for row in rows if row["source"] == provider)
    if worker not in workers:
        raise ValueError(f"worker {worker} has no {provider} slot")

    model = available_models[(workers.index(worker) + rotation) % len(available_models)]
    return {
        "model": model,
        "runtime_model": f"{provider.removesuffix('-free')}/{model}",
        "provider": provider,
        "candidate_count": len(models),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--comments", type=Path)
    parser.add_argument("--smoke-log", type=Path)
    parser.add_argument("--runtime-model")
    parser.add_argument("--outcome-file", type=Path)
    parser.add_argument("--worker", type=int)
    parser.add_argument("--rotation", type=int, default=0)
    parser.add_argument("--attempted", action="append", default=[])
    parser.add_argument("--provider", choices=("opencode-free", "openrouter-free"), default="opencode-free")
    parser.add_argument("--roster", type=Path, default=Path(".github/free-model-factories.tsv"))
    args = parser.parse_args()
    if args.smoke_log is not None:
        if not args.runtime_model or args.outcome_file is None:
            parser.error("--smoke-log requires --runtime-model and --outcome-file")
        record_smoke_failure(
            args.smoke_log.read_text(encoding="utf-8"),
            args.runtime_model,
            args.outcome_file,
        )
        return
    if args.catalog is None or args.worker is None:
        parser.error("selection requires --catalog and --worker")
    selected = select_model(
        args.catalog.read_text(encoding="utf-8"),
        args.worker,
        args.rotation,
        args.roster,
        args.comments,
        attempted=set(args.attempted),
        provider=args.provider,
    )
    print(json.dumps(selected, sort_keys=True))


if __name__ == "__main__":
    main()

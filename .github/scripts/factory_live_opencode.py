#!/usr/bin/env python3
"""Rotate the live, proven-free OpenCode catalog over durable factory identities."""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from factory_model_catalog import parse_opencode_models_text
from factory_roster import load_roster_rows, opencode_model_is_free


MODEL_UNAVAILABLE_RE = re.compile(
    r"Error:\s*Model unavailable:\s*(?P<model>\S+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ModelCooldown:
    """One model temporarily excluded due to smoke failure."""

    model: str
    reason: str
    expires_at: int  # Unix timestamp


@dataclass
class CooldownRegistry:
    """Manage model cooldowns across multiple runs."""

    cooldowns: dict[str, ModelCooldown] = field(default_factory=dict)
    cooldown_duration: int = 21600  # 6 hours in seconds

    def is_cooldown(self, model: str) -> bool:
        """Return True if the model is currently in cooldown."""
        if model not in self.cooldowns:
            return False
        cooldown = self.cooldowns[model]
        return time.time() < cooldown.expires_at

    def add_cooldown(self, model: str, reason: str) -> None:
        """Add or extend a cooldown for a model."""
        expires_at = int(time.time()) + self.cooldown_duration
        self.cooldowns[model] = ModelCooldown(model, reason, expires_at)

    def remove_cooldown(self, model: str) -> None:
        """Remove a model from cooldown."""
        self.cooldowns.pop(model, None)

    def load_from_file(self, path: Path) -> None:
        """Load cooldowns from a JSON file."""
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                for item in data.get("cooldowns", []):
                    model = item.get("model")
                    expires_at = item.get("expires_at")
                    if model and expires_at and isinstance(expires_at, int):
                        self.cooldowns[model] = ModelCooldown(model, "smoke_failure", expires_at)
        except (OSError, json.JSONDecodeError):
            pass

    def save_to_file(self, path: Path) -> None:
        """Save cooldowns to a JSON file."""
        cooldown_list = [
            {"model": cd.model, "reason": cd.reason, "expires_at": cd.expires_at}
            for cd in self.cooldowns.values()
        ]
        data = {"cooldowns": cooldown_list}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def free_models(raw_catalog: str) -> list[str]:
    """Cost metadata wins over names: never silently select a paid model."""
    catalog = parse_opencode_models_text(raw_catalog, "opencode")
    return sorted(
        entry.model_id
        for entry in catalog.entries
        if not entry.cost_is_paid
        and (entry.cost_is_zero or opencode_model_is_free(entry.model_id))
    )


def parse_trusted_attempt_evidence(comments: list[dict[str, Any]]) -> dict[tuple[str, str], str]:
    """Parse trusted attempt evidence from registry comments.

    Returns a mapping of (provider, model) to outcome.
    Only trusted comments are considered; untrusted, malformed, or stale records are ignored.
    """
    from factory_work_policy import comment_is_trusted

    outcome_pattern = re.compile(r"^\s*outcome:\s*(?P<outcome>[a-z][a-z0-9_]+)\s*$")
    updated_pattern = re.compile(r"^\s*updated:\s*(?P<updated>\S+)\s*$")
    provider_pattern = re.compile(r"^\s*Source:\s*(?P<provider>\S+)\s*$")
    model_pattern = re.compile(r"^\s*Model:\s*(?P<model>\S+)\s*$")

    evidence: dict[tuple[str, str], str] = {}

    for comment in comments:
        if not comment_is_trusted(comment):
            continue

        body = str(comment.get("body") or "")

        # Skip comments without the expected markers
        if "outcome:" not in body or "updated:" not in body:
            continue

        provider_match = provider_pattern.search(body)
        model_match = model_pattern.search(body)
        outcome_match = outcome_pattern.search(body)
        updated_match = updated_pattern.search(body)

        if not all([provider_match, model_match, outcome_match, updated_match]):
            continue

        outcome = outcome_match.group("outcome")
        if outcome in {"control_plane_failure", "environment_failure"}:
            continue

        evidence[(provider_match.group("provider"), model_match.group("model"))] = outcome

    return evidence


def filter_unavailable_models(
    models: list[str],
    trusted_evidence: dict[tuple[str, str], str],
    cooldown_registry: CooldownRegistry,
) -> list[str]:
    """Filter out models that are unavailable based on trusted evidence and cooldown.

    Returns only models that are:
    1. Not in cooldown
    2. Have no permanent unavailable evidence (model_unavailable, model_retired_410)
    """
    available = []
    for model in models:
        key = ("opencode-free", model)

        # Skip if in cooldown
        if cooldown_registry.is_cooldown(model):
            continue

        # Skip if has permanent unavailable evidence
        if trusted_evidence.get(key) in {"model_unavailable", "model_retired_410"}:
            continue

        available.append(model)

    return available


def classify_smoke_failure(log_content: str, runtime_model: str) -> tuple[bool, str]:
    """Classify the exact smoke failure.

    Returns a tuple of (is_unavailable, reason).
    """
    match = MODEL_UNAVAILABLE_RE.search(log_content)
    if match:
        model = match.group("model")
        return (True, f"Model unavailable: {model}")

    return (False, "Smoke test failed for other reasons")


def select_model(
    raw_catalog: str,
    worker: int,
    rotation: int,
    roster_path: Path,
    comments_path: Path | None = None,
    cooldown_file: Path | None = None,
) -> dict[str, str | int]:
    """Rotate all free models without assigning duplicate permanent pins.

    Consults trusted registry attempt comments and applies model cooldowns.
    """
    models = free_models(raw_catalog)
    if not models:
        raise ValueError("OpenCode catalog has no provably free models")

    # Load trusted evidence from registry comments
    trusted_evidence: dict[tuple[str, str], str] = {}
    if comments_path and comments_path.exists():
        try:
            comments_payload = json.loads(comments_path.read_text(encoding="utf-8"))
            trusted_evidence = parse_trusted_attempt_evidence(comments_payload)
        except (OSError, json.JSONDecodeError):
            pass

    # Load cooldowns from file
    cooldown_registry = CooldownRegistry()
    if cooldown_file:
        cooldown_registry.load_from_file(cooldown_file)

    # Filter out unavailable models
    available_models = filter_unavailable_models(models, trusted_evidence, cooldown_registry)

    if not available_models:
        raise ValueError(
            f"All {len(models)} candidates are unavailable or in cooldown. "
            f"Available: {available_models}, Unavailable: {[m for m in models if m not in available_models]}"
        )

    rows = load_roster_rows(roster_path)
    workers = sorted(
        int(row["worker"]) for row in rows if row["source"] == "opencode-free"
    )
    if worker not in workers:
        raise ValueError(f"worker {worker} has no OpenCode free slot")

    model = available_models[(workers.index(worker) + rotation) % len(available_models)]
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

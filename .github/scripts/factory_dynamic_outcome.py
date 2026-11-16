#!/usr/bin/env python3
"""Classify live provider-derived worker sessions with the canonical legacy rules.

The model roster was removed in #5213; the trusted Actions collector now sees
a dynamic slot marker rather than the historical "Factory N locked" marker.
This adapter restores the equivalent metadata before calling the existing
classifier. Only executed provider rejection text can refine its outcome.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

_CLASSIFIER = Path(__file__).with_name("classify-fixed-model-run.py")
_SLOT = re.compile(
    r"Factory (?P<worker>\d+) assigned dynamic provider slot: "
    r"source=(?P<source>\S+) configured=(?P<configured>true|false)", re.I
)
_MODEL = re.compile(
    r"\[factory:(?P<worker>\d+)\]\[source:(?P<source>[^\]\n]+)\]"
    r"\[model:(?P<model>[^\]\n]+)\]"
)
_COOLING = re.compile(
    r"factory catalog: [^\n]+: catalog contained no eligible candidates outside cooldown", re.I
)
_ACCOUNT_CREDITS = re.compile(
    r"add usage credits or subscribe|api key budget limit exceeded", re.I
)
_MODEL_ACCESS = re.compile(r"free tier users do not have access to this model", re.I)


def _canonical() -> Any:
    spec = importlib.util.spec_from_file_location("factory_canonical_log_classifier", _CLASSIFIER)
    if spec is None or spec.loader is None:
        raise RuntimeError("canonical factory log classifier unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def classify(log: str) -> dict[str, Any]:
    canonical = _canonical()
    # The old marker still exists for historical and explicitly pinned jobs.
    if canonical.LOCK_RE.search(log):
        return asdict(canonical.classify(log))
    match = _SLOT.search(log)
    if match is None:
        return asdict(canonical.classify(log))
    worker, source = match["worker"], match["source"]
    configured = match["configured"].lower() == "true"
    model_event = next(
        (event for event in reversed(list(_MODEL.finditer(log)))
         if event["worker"] == worker and event["source"] == source),
        None,
    )
    if model_event is None:
        if _COOLING.search(log):
            return asdict(canonical.Result(
                worker=worker, source=source, configured=configured,
                outcome="HEALTHY / IDLE", outcome_class="no_work",
                detail="provider catalog has no candidates outside existing cooldown",
            ))
        return asdict(canonical.Result(
            worker=worker, source=source, configured=configured,
            outcome="CONTROL PLANE FAILURE", outcome_class="control_plane_failure",
            detail="dynamic provider slot failed before selecting a model",
        ))
    model = model_event["model"]
    # A previous candidate's quota error cannot classify a later candidate.
    # The trusted worker prints this boundary immediately before each run_agent.
    boundary = log.rfind("FACTORY_EXECUTION_CANDIDATE: source=")
    execution_log = log[boundary:] if boundary >= 0 else log
    runtime_match = re.search(r"FACTORY_EXECUTION_CANDIDATE: source=\S+ model=\S+ runtime=(\S+)", execution_log)
    if runtime_match is None:
        runtime_match = re.search(r"(?m)^.*\bFACTORY_RUNTIME_MODEL:\s*(\S+)", log)
    runtime = runtime_match[1] if runtime_match else f"{source}/{model}"
    lock = (
        f"Factory {worker} locked: source={source} model={model} "
        f"runtime={runtime} minute=:00 scheduler=dynamic configured={str(configured).lower()}\n"
    )
    result = canonical.classify(lock + execution_log)
    # Account-wide refusal is different from one inaccessible model. Do not
    # turn a failed model into a provider-wide outage or rate limit.
    executed_lines = "\n".join(
        line for line in execution_log.splitlines() if "\x1b[36;1m" not in line
    )
    if _ACCOUNT_CREDITS.search(executed_lines):
        result = replace(result, outcome="PROVIDER QUOTA", outcome_class="provider_quota",
                         detail="provider account usage credits or key budget exhausted")
    elif _MODEL_ACCESS.search(executed_lines):
        result = replace(result, outcome="MODEL MISSING", outcome_class="model_unavailable",
                         detail="provider account tier denied this model; other models remain eligible")
    return asdict(result)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(classify(args.log.read_text(encoding="utf-8", errors="replace")),
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

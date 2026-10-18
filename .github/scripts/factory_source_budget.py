#!/usr/bin/env python3
"""Daily dispatch caps for metered free providers (OrcaRouter, Requesty).

Free OpenAI-compatible accounts publish small per-account daily request
limits. One factory session is many model requests, so the factory caps how
many Entry runs a whole *source* may start per UTC day. The count comes from
the Actions run history of ``free-model-factory-entry.yml`` (run titles are
``Factory N · fixed-model entry``), so no extra durable state is needed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path

GITHUB_DIR = Path(__file__).resolve().parents[1]
BUDGETS_PATH = GITHUB_DIR / "factory-source-budgets.json"
MANIFEST_PATH = GITHUB_DIR / "free-model-factories.tsv"
ENTRY_TITLE_RE = re.compile(r"^Factory (?P<worker>\d+) · fixed-model entry$")


def load_budgets(path: Path | str = BUDGETS_PATH) -> dict[str, int]:
    """Return ``{source: max_dispatches_per_utc_day}``; a missing file means no caps."""
    path = Path(path)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("unsupported factory-source-budgets schema_version")
    caps: dict[str, int] = {}
    for source, entry in (data.get("sources") or {}).items():
        cap = entry.get("max_dispatches_per_utc_day")
        if not isinstance(cap, int) or isinstance(cap, bool) or cap < 0:
            raise ValueError(f"{source}: max_dispatches_per_utc_day must be a non-negative integer")
        caps[str(source)] = cap
    return caps


def load_request_budgets(path: Path | str = BUDGETS_PATH) -> dict[str, dict[str, int]]:
    """Return ``{source: {max_requests_per_utc_day: int, max_requests_per_dispatch: int, max_requests_per_minute: int}}``; a missing file means no caps."""
    path = Path(path)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("unsupported factory-source-budgets schema_version")
    caps: dict[str, dict[str, int]] = {}
    for source, entry in (data.get("sources") or {}).items():
        request_cap = entry.get("max_requests_per_utc_day")
        dispatch_cap = entry.get("max_requests_per_dispatch")
        minute_cap = entry.get("max_requests_per_minute")
        
        if request_cap is not None and (not isinstance(request_cap, int) or isinstance(request_cap, bool) or request_cap < 0):
            raise ValueError(f"{source}: max_requests_per_utc_day must be a non-negative integer")
        if dispatch_cap is not None and (not isinstance(dispatch_cap, int) or isinstance(dispatch_cap, bool) or dispatch_cap < 0):
            raise ValueError(f"{source}: max_requests_per_dispatch must be a non-negative integer")
        if minute_cap is not None and (not isinstance(minute_cap, int) or isinstance(minute_cap, bool) or minute_cap < 0):
            raise ValueError(f"{source}: max_requests_per_minute must be a non-negative integer")
        
        if request_cap is not None:
            caps[str(source)] = {
                "max_requests_per_utc_day": request_cap,
                "max_requests_per_dispatch": dispatch_cap or 45,
                "max_requests_per_minute": minute_cap or 10
            }
    return caps


def load_protected_workers(path: Path | str = BUDGETS_PATH) -> set[int]:
    """Return set of protected worker IDs exempt from budget checks."""
    path = Path(path)
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("unsupported factory-source-budgets schema_version")
    protected = data.get("protected_workers")
    if protected is None:
        return set()
    if not isinstance(protected, list):
        raise ValueError("protected_workers must be a list")
    return {int(w) for w in protected if isinstance(w, int) and w > 0}


def load_source_scoped_retirement_sources(path: Path | str = BUDGETS_PATH) -> set[str]:
    """Return set of sources that use source-scoped retirement keys."""
    path = Path(path)
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("unsupported factory-source-budgets schema_version")
    sources = data.get("source_scoped_retirement_sources")
    if sources is None:
        return set()
    if not isinstance(sources, list):
        raise ValueError("source_scoped_retirement_sources must be a list")
    return {str(s) for s in sources if isinstance(s, str)}


def worker_sources(path: Path | str = MANIFEST_PATH) -> dict[str, str]:
    """Map worker id to roster source from the fixed-model manifest."""
    mapping: dict[str, str] = {}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.startswith("#"):
            continue
        fields = raw.split("\t")
        if len(fields) >= 2 and fields[0].strip().isdigit():
            mapping[fields[0].strip()] = fields[1].strip()
    return mapping


def count_dispatches(
    titles: Iterable[str], sources: Mapping[str, str], budgeted: Iterable[str]
) -> dict[str, int]:
    """Count today's Entry runs per budgeted source from run titles."""
    wanted = set(budgeted)
    counts = dict.fromkeys(wanted, 0)
    for title in titles:
        match = ENTRY_TITLE_RE.match(title or "")
        if not match:
            continue
        source = sources.get(match.group("worker"))
        if source in wanted:
            counts[source] += 1
    return counts


def estimate_requests_from_dispatches(
    titles: Iterable[str], sources: Mapping[str, str], budgeted: Iterable[str], request_budgets: dict[str, dict[str, int]]
) -> dict[str, int]:
    """Estimate today's requests per budgeted source from run titles, using conservative estimates."""
    wanted = set(budgeted)
    counts = dict.fromkeys(wanted, 0)
    for title in titles:
        match = ENTRY_TITLE_RE.match(title or "")
        if not match:
            continue
        source = sources.get(match.group("worker"))
        if source in wanted and source in request_budgets:
            # Use conservative estimate based on max_requests_per_dispatch
            counts[source] += request_budgets[source]["max_requests_per_dispatch"]
    return counts


def would_exceed_request_budget(
    worker: str, sources: Mapping[str, str], request_budgets: dict[str, dict[str, int]], 
    dispatch_titles: Iterable[str] | None = None, request_counts: dict[str, int] | None = None
) -> str | None:
    """Check if dispatching a worker would exceed its request budget."""
    if not str(worker).isdigit() or int(worker) in load_protected_workers():
        return None
    
    source = sources.get(str(worker))
    if source is None or source not in request_budgets:
        return None
    
    budget = request_budgets[source]
    
    # Calculate current estimated requests
    if request_counts is None:
        if dispatch_titles is None:
            dispatch_titles = todays_entry_titles()
        request_counts = estimate_requests_from_dispatches(dispatch_titles, sources, [source], request_budgets)
    
    current_requests = request_counts.get(source, 0)
    
    # Check if adding one more dispatch (with max requests) would exceed daily limit
    if current_requests + budget["max_requests_per_dispatch"] > budget["max_requests_per_utc_day"]:
        return (f"Factory {worker} source {source} would exceed daily request budget "
                f"({current_requests + budget['max_requests_per_dispatch']}/{budget['max_requests_per_utc_day']} UTC today)")
    
    return None


def todays_entry_titles(now: datetime | None = None) -> list[str]:
    """Return Entry run titles created since 00:00 UTC today (via gh api)."""
    now = now or datetime.now(timezone.utc)
    repo = os.environ.get("GITHUB_REPOSITORY", "JoshCLWren/comic-pile")
    day = now.strftime("%Y-%m-%d")
    output = subprocess.run(
        [
            "gh",
            "api",
            "--paginate",
            f"repos/{repo}/actions/workflows/free-model-factory-entry.yml/runs"
            f"?created=%3E%3D{day}&per_page=100",
            "--jq",
            ".workflow_runs[].display_title",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    ).stdout
    return [line for line in output.splitlines() if line.strip()]


def exhausted_sources(
    titles: Iterable[str] | None = None,
    *,
    caps: Mapping[str, int] | None = None,
    sources: Mapping[str, str] | None = None,
) -> dict[str, tuple[int, int]]:
    """Return ``{source: (used, cap)}`` for budgeted sources at or over cap today."""
    caps = load_budgets() if caps is None else caps
    if not caps:
        return {}
    sources = worker_sources() if sources is None else sources
    if not any(source in caps for source in sources.values()):
        return {}
    titles = todays_entry_titles() if titles is None else titles
    counts = count_dispatches(titles, sources, caps)
    return {source: (used, caps[source]) for source, used in counts.items() if used >= caps[source]}


def exhausted_request_sources(
    titles: Iterable[str] | None = None,
    *,
    request_budgets: dict[str, dict[str, int]] | None = None,
    sources: Mapping[str, str] | None = None,
) -> dict[str, tuple[int, int]]:
    """Return ``{source: (estimated_used, cap)}`` for sources that have exhausted their request budget."""
    request_budgets = load_request_budgets() if request_budgets is None else request_budgets
    if not request_budgets:
        return {}
    sources = worker_sources() if sources is None else sources
    if not any(source in request_budgets for source in sources.values()):
        return {}
    titles = todays_entry_titles() if titles is None else titles
    counts = estimate_requests_from_dispatches(titles, sources, request_budgets, request_budgets)
    return {
        source: (used, request_budgets[source]["max_requests_per_utc_day"]) 
        for source, used in counts.items() 
        if used >= request_budgets[source]["max_requests_per_utc_day"]
    }


def budget_block_reason(
    worker: str,
    *,
    titles: Iterable[str] | None = None,
    caps: Mapping[str, int] | None = None,
    sources: Mapping[str, str] | None = None,
    request_budgets: dict[str, dict[str, int]] | None = None,
) -> str | None:
    """Return why a worker's source is out of daily dispatch or request budget, else None."""
    if not str(worker).isdigit() or int(worker) in load_protected_workers():
        return None
    sources = worker_sources() if sources is None else sources
    caps = load_budgets() if caps is None else caps
    source = sources.get(str(worker))
    if source is None or source not in caps:
        return None
    
    # Check dispatch budget first
    try:
        exhausted = exhausted_sources(titles, caps=caps, sources=sources)
    except (OSError, subprocess.SubprocessError) as exc:
        # Fail closed for metered sources only: an unreadable run history must
        # not risk blowing a small account budget.
        return f"Factory {worker} source {source} budget could not be verified ({exc.__class__.__name__})"
    if source in exhausted:
        used, cap = exhausted[source]
        return f"Factory {worker} source {source} reached its daily dispatch budget ({used}/{cap} UTC today)"
    
    # Check request budget if available
    if request_budgets is None:
        request_budgets = load_request_budgets()
    if source in request_budgets:
        try:
            request_exhausted = exhausted_request_sources(titles, request_budgets=request_budgets, sources=sources)
        except (OSError, subprocess.SubprocessError) as exc:
            return f"Factory {worker} source {source} request budget could not be verified ({exc.__class__.__name__})"
        if source in request_exhausted:
            used, cap = request_exhausted[source]
            return f"Factory {worker} source {source} reached its daily request budget ({used}/{cap} UTC today)"
        
        # Check if dispatching this worker would exceed request budget
        would_exceed = would_exceed_request_budget(worker, sources, request_budgets, titles)
        if would_exceed:
            return would_exceed
    
    return None


def filter_workers(
    workers: list[str],
    *,
    titles: Iterable[str] | None = None,
    caps: Mapping[str, int] | None = None,
    sources: Mapping[str, str] | None = None,
    request_budgets: dict[str, dict[str, int]] | None = None,
) -> tuple[list[str], list[str]]:
    """Drop workers whose source budget is exhausted; also cap within this batch."""
    caps = load_budgets() if caps is None else caps
    if not caps:
        return list(workers), []
    sources = worker_sources() if sources is None else sources
    if request_budgets is None:
        request_budgets = load_request_budgets()
    
    if titles is None and (any(sources.get(str(w)) in caps for w in workers) or 
                          any(sources.get(str(w)) in request_budgets for w in workers)):
        try:
            titles = todays_entry_titles()
        except (OSError, subprocess.SubprocessError) as exc:
            kept = [w for w in workers if sources.get(str(w)) not in caps and sources.get(str(w)) not in request_budgets]
            dropped = [w for w in workers if sources.get(str(w)) in caps or sources.get(str(w)) in request_budgets]
            return kept, [
                f"Factory {w} skipped: metered source budget could not be verified ({exc.__class__.__name__})"
                for w in dropped
            ]
    
    # Check dispatch budgets
    dispatch_counts = count_dispatches(titles or [], sources, caps)
    request_counts: dict[str, int] = estimate_requests_from_dispatches(titles or [], sources, request_budgets, request_budgets)
    kept: list[str] = []
    messages: list[str] = []
    
    for worker in workers:
        source = sources.get(str(worker))
        worker_id = int(str(worker))
        
        # Skip protected workers
        if worker_id in load_protected_workers():
            kept.append(worker)
            continue
            
        # Check if worker has a budgeted source
        has_dispatch_budget = source is not None and source in caps
        has_request_budget = source is not None and source in request_budgets
        
        if not has_dispatch_budget and not has_request_budget:
            kept.append(worker)
            continue
            
        # Check dispatch budget
        if has_dispatch_budget and dispatch_counts[source] >= caps[source]:
            messages.append(
                f"Factory {worker} skipped: source {source} daily dispatch budget "
                f"{dispatch_counts[source]}/{caps[source]} reached (UTC day)"
            )
            continue
            
        # Check request budget and whether this dispatch would exceed it
        if has_request_budget:
            would_exceed = would_exceed_request_budget(worker, sources, request_budgets, None, request_counts)
            if would_exceed:
                messages.append(f"Factory {worker} skipped: {would_exceed}")
                continue
                
        # Worker passes all checks
        if has_dispatch_budget:
            dispatch_counts[source] += 1
        if has_request_budget:
            request_counts[source] = request_counts.get(source, 0) + request_budgets[source]["max_requests_per_dispatch"]
        kept.append(worker)
        
    return kept, messages


def main(argv: list[str] | None = None) -> int:
    """CLI: ``filter`` reads a JSON worker array on stdin; ``status`` prints usage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("filter", "status", "validate"))
    args = parser.parse_args(argv)
    if args.command == "validate":
        load_budgets()
        load_request_budgets()
        return 0
    if args.command == "status":
        caps = load_budgets()
        request_budgets = load_request_budgets()
        sources = worker_sources()
        titles = todays_entry_titles()
        
        # Dispatch status
        dispatch_counts = count_dispatches(titles, sources, caps)
        dispatch_status = {}
        for source in caps:
            dispatch_status[source] = {
                "used": dispatch_counts.get(source, 0),
                "cap": caps[source],
                "type": "dispatches"
            }
        
        # Request status
        request_counts = estimate_requests_from_dispatches(titles, sources, request_budgets, request_budgets)
        for source in request_budgets:
            if source not in dispatch_status:
                dispatch_status[source] = {"used": 0, "cap": 0, "type": "requests"}
            dispatch_status[source].update({
                "estimated_requests": request_counts.get(source, 0),
                "request_cap": request_budgets[source]["max_requests_per_utc_day"],
                "max_per_dispatch": request_budgets[source]["max_requests_per_dispatch"],
                "max_per_minute": request_budgets[source]["max_requests_per_minute"],
                "type": "requests"
            })
        
        print(json.dumps(dispatch_status, separators=(",", ":")))
        return 0
    workers = [str(item) for item in json.load(sys.stdin)]
    kept, messages = filter_workers(workers, request_budgets=load_request_budgets())
    for message in messages:
        print(message, file=sys.stderr)
    print(json.dumps(kept, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Read-only GitHub report on the FIRST CI head of recent Rust pull requests.

Requires an authenticated gh CLI. No status updates, PR edits or API writes.
The first observed pull_request workflow SHA is a proxy for the PR's opening
head; historical run retention and missing PR associations may limit coverage.
Unclassified failures are deliberately not called model mistakes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from collections import Counter
from datetime import date
from pathlib import Path


def github(endpoint: str) -> object:
    """Read one GitHub REST response using the installed gh authentication."""
    completed = subprocess.run(
        ["gh", "api", endpoint],
        check=True,
        text=True,
        capture_output=True,
        env=os.environ.copy(),
    )
    return json.loads(completed.stdout)


def records(value: object) -> list[dict[str, object]]:
    """Narrow untrusted JSON objects to plain dictionaries."""
    if not isinstance(value, list):
        return []
    return [
        {str(key): member for key, member in row.items()}
        for row in value
        if isinstance(row, dict)
    ]


def value_str(row: dict[str, object], key: str) -> str:
    """Return a string property, or an empty string when missing."""
    value = row.get(key)
    return value if isinstance(value, str) else ""


def value_int(row: dict[str, object], key: str) -> int:
    """Return an integer property without coercing arbitrary JSON values."""
    value = row.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def paged(repo: str, path: str, pages: int, *, collection: str = "") -> list[dict[str, object]]:
    """Fetch a bounded, explicitly paged read-only GitHub collection."""
    output: list[dict[str, object]] = []
    for page in range(1, pages + 1):
        sep = "&" if "?" in path else "?"
        payload = github(f"repos/{repo}/{path}{sep}per_page=100&page={page}")
        if collection:
            if not isinstance(payload, dict):
                break
            payload = payload.get(collection)
        batch = records(payload)
        output.extend(batch)
        if len(batch) < 100:
            break
    return output


def provenance(body: str, label: str) -> str:
    """Extract explicit model/worker provenance; never infer an identity."""
    match = re.search(rf"(?im)^{re.escape(label)}:\s*(.+?)\s*$", body)
    return match.group(1).strip() if match else "unknown"


def is_rust_pr(repo: str, number: int) -> bool:
    """Select by actual changed Rust/manifests, not PR-title wording."""
    files = paged(repo, f"pulls/{number}/files", 5)
    return any(
        (name := value_str(item, "filename")).endswith(".rs")
        or name in {"Cargo.toml", "Cargo.lock"}
        or (name.startswith("native/roll-service/") and name.endswith(".toml"))
        for item in files
    )


def first_head(runs: list[dict[str, object]]) -> tuple[str, list[dict[str, object]]]:
    """Return earliest observed CI SHA and every run at that same SHA."""
    if not runs:
        return "", []
    earliest = min(runs, key=lambda run: value_str(run, "created_at"))
    sha = value_str(earliest, "head_sha")
    return sha, [run for run in runs if value_str(run, "head_sha") == sha]


def result_for(runs: list[dict[str, object]]) -> str:
    """Classify observed first-head workflow conclusions conservatively."""
    if not runs:
        return "no-runs"
    conclusions = {value_str(run, "conclusion") for run in runs}
    if conclusions & {"failure", "timed_out", "action_required"}:
        return "failed"
    if conclusions & {"", "neutral", "skipped", "stale"}:
        return "incomplete"
    if "cancelled" in conclusions:
        return "cancelled"
    if conclusions == {"success"}:
        return "passed"
    return "incomplete"


def jobs_for_failures(repo: str, runs: list[dict[str, object]]) -> list[str]:
    """Report failed job names without guessing infra versus code root cause."""
    names: list[str] = []
    for run in runs:
        if value_str(run, "conclusion") not in {"failure", "timed_out", "action_required"}:
            continue
        run_id = value_int(run, "id")
        if not run_id:
            continue
        jobs = paged(repo, f"actions/runs/{run_id}/jobs", 3, collection="jobs")
        names.extend(
            value_str(job, "name") or "unnamed job"
            for job in jobs
            if value_str(job, "conclusion") in {"failure", "timed_out", "action_required"}
        )
    return sorted(set(names))


def report(repo: str, since: str, pages: int) -> dict[str, object]:
    """Read GitHub pull requests and workflow runs; summarize first heads."""
    pulls = paged(repo, "pulls?state=all", pages)
    runs = paged(repo, "actions/runs?event=pull_request", pages, collection="workflow_runs")
    output: list[dict[str, object]] = []
    for pr in pulls:
        if value_str(pr, "created_at")[:10] < since:
            continue
        number = value_int(pr, "number")
        if not number or not is_rust_pr(repo, number):
            continue
        related = [
            run
            for run in runs
            if any(
                value_int(link, "number") == number
                for link in records(run.get("pull_requests"))
            )
        ]
        sha, initial_runs = first_head(related)
        body = value_str(pr, "body")
        status = result_for(initial_runs)
        output.append(
            {
                "number": number,
                "url": value_str(pr, "html_url"),
                "created_at": value_str(pr, "created_at"),
                "model": provenance(body, "Model"),
                "worker": provenance(body, "Worker"),
                "first_observed_head": sha or None,
                "first_head_result": status,
                "failed_jobs": jobs_for_failures(repo, initial_runs) if status == "failed" else [],
                "root_cause": "unclassified" if status == "failed" else None,
            }
        )
    return {
        "repository": repo,
        "since": since,
        "attribution": "PR-body Model and Worker fields only",
        "head_definition": "earliest retained pull_request Actions run, grouped by head_sha",
        "coverage_limit": f"last {pages * 100} PRs and {pages * 100} workflow runs",
        "pull_requests": sorted(output, key=lambda item: value_int(item, "number"), reverse=True),
    }


def markdown(data: dict[str, object]) -> str:
    """Render first-head CI quality grouped by explicitly identified model."""
    prs = records(data.get("pull_requests"))
    groups: dict[str, list[dict[str, object]]] = {}
    for pr in prs:
        groups.setdefault(value_str(pr, "model"), []).append(pr)
    lines = [
        "# Rust first-head CI quality",
        "",
        f"Repository: {data['repository']}, PRs opened since {data['since']}",
        "",
        "First head means earliest retained PR-triggered Actions SHA, not the first commit.",
        "Failures are not automatically attributed to the model; infra versus code is unclassified.",
        "",
        "| Model | PRs | Passed | Failed | Incomplete/cancelled/no runs |",
        "|---|---:|---:|---:|---:|",
    ]
    for model, group in sorted(groups.items()):
        counts = Counter(value_str(pr, "first_head_result") for pr in group)
        lines.append(
            f"| {model.replace('|', '/')} | {len(group)} | {counts['passed']} | "
            f"{counts['failed']} | "
            f"{len(group) - counts['passed'] - counts['failed']} |"
        )
    lines.extend(["", "## Failed first heads", ""])
    for pr in prs:
        if value_str(pr, "first_head_result") != "failed":
            continue
        jobs = pr.get("failed_jobs")
        labels = ", ".join(str(name) for name in jobs) if isinstance(jobs, list) else ""
        lines.append(f"- PR #{pr['number']} ({pr['model']}): {labels or 'jobs unavailable'}")
    if not groups:
        lines.append("No matching Rust PRs within the selected retrieval window.")
    lines.extend(["", f"Coverage limit: {data['coverage_limit']}. "
                  "Missing or expired runs remain unknown, never counted as green.", ""])
    return "\n".join(lines)


def main() -> None:
    """Produce a JSON or Markdown report without mutating GitHub."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="JoshCLWren/comic-pile")
    parser.add_argument("--since", default="2026-10-29")
    parser.add_argument("--pages", type=int, default=10)
    parser.add_argument("--format", choices=["json", "markdown"], default="markdown")
    parser.add_argument("--input", type=Path, help="Render an existing JSON report without new API calls")
    args = parser.parse_args()
    date.fromisoformat(args.since)
    if not 1 <= args.pages <= 30:
        parser.error("--pages must be between 1 and 30")
    data = (
        json.loads(args.input.read_text(encoding="utf-8"))
        if args.input is not None
        else report(args.repo, args.since, args.pages)
    )
    print(json.dumps(data, indent=2) if args.format == "json" else markdown(data))


if __name__ == "__main__":
    main()

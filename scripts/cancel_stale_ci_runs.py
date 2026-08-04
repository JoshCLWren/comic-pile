#!/usr/bin/env python3
"""Cancel superseded ComicPile CI runs for one pull-request branch."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final

ACTIVE_RUN_STATUSES: Final[frozenset[str]] = frozenset(
    {"queued", "in_progress", "requested", "waiting", "pending"}
)
API_VERSION: Final[str] = "2022-11-28"


@dataclass(frozen=True)
class WorkflowRun:
    """Minimal workflow-run metadata required for cancellation."""

    run_id: int
    head_branch: str
    head_sha: str
    status: str
    html_url: str


def select_superseded_runs(
    runs: Iterable[Mapping[str, object]],
    *,
    head_branch: str,
    current_sha: str,
) -> list[WorkflowRun]:
    """Return active older runs for the same pull-request branch.

    Args:
        runs: GitHub workflow-run payloads.
        head_branch: Current pull request head branch.
        current_sha: Current pull request head SHA.

    Returns:
        Older active runs that are safe to cancel, ordered by run id.
    """
    selected: list[WorkflowRun] = []
    for run in runs:
        run_id = run.get("id")
        run_branch = run.get("head_branch")
        run_sha = run.get("head_sha")
        status = run.get("status")
        html_url = run.get("html_url")
        event = run.get("event")

        if not isinstance(run_id, int):
            continue
        if event != "pull_request":
            continue
        if run_branch != head_branch or run_sha == current_sha:
            continue
        if status not in ACTIVE_RUN_STATUSES:
            continue

        selected.append(
            WorkflowRun(
                run_id=run_id,
                head_branch=str(run_branch),
                head_sha=str(run_sha),
                status=str(status),
                html_url=str(html_url or ""),
            )
        )

    return sorted(selected, key=lambda run: run.run_id)


def _request_json(url: str, token: str) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": API_VERSION,
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise RuntimeError("GitHub returned an unexpected workflow-runs payload")
    return payload


def _cancel_run(repo: str, run_id: int, token: str) -> None:
    url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/cancel"
    request = urllib.request.Request(
        url,
        method="POST",
        data=b"",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": API_VERSION,
        },
    )
    with urllib.request.urlopen(request, timeout=30):
        return


def cancel_superseded_runs(
    *,
    repo: str,
    workflow: str,
    head_branch: str,
    current_sha: str,
    token: str,
    dry_run: bool,
) -> list[WorkflowRun]:
    """Find and cancel superseded active runs for one branch.

    Args:
        repo: Repository in owner/name form.
        workflow: Workflow file name or workflow id.
        head_branch: Current pull request branch.
        current_sha: Current pull request head SHA.
        token: GitHub token with Actions write permission.
        dry_run: Report matching runs without cancelling them.

    Returns:
        Matching superseded runs.
    """
    encoded_workflow = urllib.parse.quote(workflow, safe="")
    query = urllib.parse.urlencode(
        {
            "event": "pull_request",
            "branch": head_branch,
            "per_page": 100,
        }
    )
    url = (
        f"https://api.github.com/repos/{repo}/actions/workflows/"
        f"{encoded_workflow}/runs?{query}"
    )
    payload = _request_json(url, token)
    raw_runs = payload.get("workflow_runs", [])
    if not isinstance(raw_runs, list):
        raise RuntimeError("GitHub returned workflow_runs in an unexpected shape")

    selected = select_superseded_runs(
        (run for run in raw_runs if isinstance(run, dict)),
        head_branch=head_branch,
        current_sha=current_sha,
    )
    for run in selected:
        action = "Would cancel" if dry_run else "Cancelling"
        print(
            f"{action} superseded {run.status} CI run {run.run_id} "
            f"at {run.head_sha[:12]} {run.html_url}".rstrip()
        )
        if not dry_run:
            _cancel_run(repo, run.run_id, token)
    return selected


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="Repository in owner/name form")
    parser.add_argument("--workflow", default="ci.yml", help="Workflow file name or id")
    parser.add_argument("--head-branch", required=True, help="Current PR head branch")
    parser.add_argument("--current-sha", required=True, help="Current PR head SHA")
    parser.add_argument("--dry-run", action="store_true", help="Report without cancelling")
    return parser.parse_args()


def main() -> int:
    """Run the stale-CI cancellation command."""
    args = _parse_args()
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("GITHUB_TOKEN is required", file=sys.stderr)
        return 2

    try:
        selected = cancel_superseded_runs(
            repo=args.repo,
            workflow=args.workflow,
            head_branch=args.head_branch,
            current_sha=args.current_sha,
            token=token,
            dry_run=args.dry_run,
        )
    except (RuntimeError, urllib.error.HTTPError, urllib.error.URLError) as error:
        print(f"Failed to inspect or cancel stale CI runs: {error}", file=sys.stderr)
        return 1

    if selected:
        print(f"Matched {len(selected)} superseded CI run(s).")
    else:
        print("No superseded CI runs found for this pull-request branch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

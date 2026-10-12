#!/usr/bin/env python3
"""Decide whether Deploy Production and factory merges must freeze.

The freeze is active only while the most recent *attempted* Deploy Production
run on ``main`` is red. Gate-blocked runs (the freeze job stopped the deploy)
and cancelled, skipped, or neutral runs do not count. Only a successful
attempted deploy lifts the freeze. Maintainers may bypass it with
``--override`` and a non-empty ``--reason``; that override is restricted to
the repository owner at the workflow layer. Factory merge drains honor the
freeze except for PRs labeled ``deploy-fix``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import TypedDict

WORKFLOW_NAME = "Deploy Production"
GATE_JOB_NAME = "Red-deploy freeze gate"
DEPLOY_FIX_LABEL = "deploy-fix"
RED_CONCLUSIONS = frozenset({"failure", "timed_out", "startup_failure"})
SUCCESS_CONCLUSIONS = frozenset({"success"})
# These completed conclusions must not lift a freeze and are not "attempted".
SKIP_RUN_CONCLUSIONS = frozenset({"cancelled", "skipped", "neutral"})
NON_ATTEMPT_JOB_CONCLUSIONS = frozenset({"", "skipped", "cancelled", "neutral"})
JOBS_PAGE_SIZE = 100
RUNS_PAGE_SIZE = 100

JobsLoader = Callable[[int], list[Mapping[str, object]] | None]


class FreezeDecision(TypedDict):
    """JSON-serializable freeze evaluation result."""

    blocked: bool
    frozen: bool
    overridden: bool
    conclusion: str | None
    run_id: int | None
    run_url: str | None
    reason: str


def workflow_runs(payload: object) -> Iterable[Mapping[str, object]]:
    """Yield workflow runs from one REST page or a slurped page list.

    Args:
        payload: Decoded GitHub workflow-runs REST response.

    Yields:
        Mapping objects representing workflow runs.

    Raises:
        ValueError: The response does not have the expected GitHub shape.

    """
    pages: list[object]
    if isinstance(payload, list):
        pages = payload
    else:
        pages = [payload]

    for page in pages:
        if not isinstance(page, Mapping):
            raise ValueError("workflow-runs response page must be an object")
        runs = page.get("workflow_runs")
        if not isinstance(runs, list):
            raise ValueError("workflow-runs response is missing workflow_runs")
        for run in runs:
            if not isinstance(run, Mapping):
                raise ValueError("workflow run must be an object")
            yield run


def _run_id(run: Mapping[str, object]) -> int:
    """Return the numeric workflow-run id.

    Args:
        run: One GitHub workflow-run object.

    Returns:
        The run id.

    Raises:
        ValueError: The run is missing a numeric id.

    """
    run_id = run.get("id")
    if not isinstance(run_id, int):
        raise ValueError("workflow run is missing its numeric id")
    return run_id


def _conclusion(run: Mapping[str, object]) -> str:
    """Return the lowercased workflow-run conclusion."""
    return str(run.get("conclusion") or "").lower()


def _jobs_from_run(run: Mapping[str, object]) -> list[Mapping[str, object]] | None:
    """Return jobs already attached to a run, if any.

    Args:
        run: Workflow-run mapping, optionally annotated with ``jobs``.

    Returns:
        Job mappings, an empty list when GitHub reported none, or ``None``
        when the caller did not attach job data.

    """
    if "jobs" not in run:
        return None
    raw = run.get("jobs")
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError("workflow run jobs must be a list")
    jobs: list[Mapping[str, object]] = []
    for job in raw:
        if not isinstance(job, Mapping):
            raise ValueError("workflow job must be an object")
        jobs.append(job)
    return jobs


def run_attempted_deploy(
    run: Mapping[str, object],
    jobs: Sequence[Mapping[str, object]] | None = None,
) -> bool | None:
    """Return whether a run actually attempted a deploy.

    A run is gate-blocked when the only job that did anything is the freeze
    gate. Those runs must not count as red and must not lift a freeze.

    Args:
        run: Workflow-run mapping.
        jobs: Optional job list. ``None`` means job data is unknown.

    Returns:
        ``True`` when a non-gate job ran, ``False`` when the run was
        gate-blocked, ``None`` when job data is unknown.

    """
    attached = jobs if jobs is not None else _jobs_from_run(run)
    if attached is None:
        return None
    for job in attached:
        name = str(job.get("name") or "")
        if name == GATE_JOB_NAME:
            continue
        conclusion = str(job.get("conclusion") or "").lower()
        if conclusion not in NON_ATTEMPT_JOB_CONCLUSIONS:
            return True
    return False


def _sort_key(run: Mapping[str, object]) -> tuple[str, int]:
    """Newest-first ordering key for one run."""
    updated = str(run.get("updated_at") or run.get("created_at") or "")
    return (updated, _run_id(run))


def latest_attempted_deploy_run(
    payload: object,
    *,
    jobs_loader: JobsLoader | None = None,
) -> Mapping[str, object] | None:
    """Return the newest completed Deploy Production run that attempted a deploy.

    Skips cancelled, skipped, and neutral runs. Skips gate-blocked runs whose
    jobs show that only the freeze gate ran. Unknown job data on a red run is
    treated as an attempted deploy so a real failure still freezes. Unknown
    job data on a successful run is not treated as a lift.

    When ``jobs_loader`` is set, jobs are fetched newest-first only until an
    attempted run is identified.

    Args:
        payload: Decoded, single-page workflow-runs response.
        jobs_loader: Optional per-run jobs fetcher.

    Returns:
        The latest attempted run mapping, or ``None`` when none exist.

    """
    eligible: list[Mapping[str, object]] = []
    for run in workflow_runs(payload):
        name = str(run.get("name") or "")
        status = str(run.get("status") or "").lower()
        if name and name != WORKFLOW_NAME:
            continue
        if status and status != "completed":
            continue
        if _conclusion(run) in SKIP_RUN_CONCLUSIONS:
            continue
        eligible.append(run)
    eligible.sort(key=_sort_key, reverse=True)
    for run in eligible:
        conclusion = _conclusion(run)
        jobs = _jobs_from_run(run)
        if jobs is None and jobs_loader is not None:
            jobs = jobs_loader(_run_id(run))
            if isinstance(run, dict):
                run["jobs"] = jobs
        attempted = run_attempted_deploy(run, jobs)
        if attempted is False:
            continue
        if attempted is None and conclusion in SUCCESS_CONCLUSIONS:
            # A green conclusion without job data might be a gate-blocked
            # run that exited 0. Do not let it lift a freeze.
            continue
        return run
    return None


def latest_completed_deploy_run(
    payload: object,
    *,
    jobs_loader: JobsLoader | None = None,
) -> Mapping[str, object] | None:
    """Return the newest attempted Deploy Production run.

    Kept as the historical name used by tests and callers. Gate-blocked and
    cancelled runs are skipped; see :func:`latest_attempted_deploy_run`.

    Args:
        payload: Decoded workflow-runs REST response.
        jobs_loader: Optional per-run jobs fetcher.

    Returns:
        The latest attempted run, or ``None``.

    """
    return latest_attempted_deploy_run(payload, jobs_loader=jobs_loader)


def evaluate_freeze(
    payload: object,
    *,
    override: bool = False,
    reason: str = "",
    jobs_loader: JobsLoader | None = None,
) -> FreezeDecision:
    """Return the freeze decision for one workflow-runs payload.

    Args:
        payload: Decoded GitHub workflow-runs REST response.
        override: Whether a maintainer marked this run as the freeze bypass.
        reason: Required explanation when ``override`` is true.
        jobs_loader: Optional per-run jobs fetcher used to skip gate-blocked
            runs without paging the full job history.

    Returns:
        JSON-serializable decision including ``blocked``, ``frozen``, the
        blocking run URL when present, and a human-readable reason.

    """
    latest = latest_attempted_deploy_run(payload, jobs_loader=jobs_loader)
    run_id = _run_id(latest) if latest is not None else None
    run_url = str((latest or {}).get("html_url") or "")
    conclusion = _conclusion(latest) if latest is not None else ""
    last_is_red = bool(latest) and conclusion in RED_CONCLUSIONS

    if override:
        stripped = reason.strip()
        if not stripped:
            return {
                "blocked": True,
                "frozen": last_is_red,
                "overridden": False,
                "conclusion": conclusion or None,
                "run_id": run_id,
                "run_url": run_url or None,
                "reason": "override_freeze requires a non-empty reason",
            }
        message = (
            "Owner override_freeze=true; proceeding despite a red "
            f"Deploy Production run ({run_url}). Reason: {stripped}"
            if last_is_red and run_url
            else f"Owner override_freeze=true. Reason: {stripped}"
        )
        return {
            "blocked": False,
            "frozen": False,
            "overridden": True,
            "conclusion": conclusion or None,
            "run_id": run_id,
            "run_url": run_url or None,
            "reason": message,
        }

    if latest is None:
        return {
            "blocked": False,
            "frozen": False,
            "overridden": False,
            "conclusion": None,
            "run_id": None,
            "run_url": None,
            "reason": "no attempted Deploy Production runs on main",
        }

    if last_is_red:
        why = (
            "Last attempted Deploy Production run on main is "
            f"{conclusion}: {run_url or f'run {run_id}'}. "
            "Factory merges are frozen except PRs labeled "
            f"{DEPLOY_FIX_LABEL}. Re-run Deploy Production with "
            "workflow_dispatch override_freeze=true and a reason after the fix "
            "is on main. Only the repository owner may override."
        )
        return {
            "blocked": True,
            "frozen": True,
            "overridden": False,
            "conclusion": conclusion,
            "run_id": run_id,
            "run_url": run_url or None,
            "reason": why,
        }

    return {
        "blocked": False,
        "frozen": False,
        "overridden": False,
        "conclusion": conclusion or None,
        "run_id": run_id,
        "run_url": run_url or None,
        "reason": (
            f"Last attempted Deploy Production run is {conclusion or 'success'}"
            + (f": {run_url}" if run_url else "")
        ),
    }


def fetch_run_jobs(run_id: int, *, repository: str | None = None) -> list[Mapping[str, object]] | None:
    """Load jobs for one workflow run via ``gh api``.

    Args:
        run_id: GitHub workflow-run id.
        repository: ``owner/repo``. Defaults to ``GITHUB_REPOSITORY``.

    Returns:
        Job mappings, or ``None`` when the jobs API call fails.

    """
    repo = repository or os.environ.get("GITHUB_REPOSITORY", "JoshCLWren/comic-pile")
    command = [
        "gh",
        "api",
        f"repos/{repo}/actions/runs/{run_id}/jobs?per_page={JOBS_PAGE_SIZE}",
    ]
    try:
        proc = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"warning: jobs API failed for run {run_id}: {exc}", file=sys.stderr)
        return None
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        print(
            f"warning: jobs API failed for run {run_id}: {detail or proc.returncode}",
            file=sys.stderr,
        )
        return None
    try:
        payload = json.loads(proc.stdout) if proc.stdout.strip() else None
    except json.JSONDecodeError as exc:
        print(f"warning: jobs API returned invalid JSON for run {run_id}: {exc}", file=sys.stderr)
        return None
    if not isinstance(payload, dict):
        print(f"warning: jobs API payload for run {run_id} was not an object", file=sys.stderr)
        return None
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        print(f"warning: jobs API payload for run {run_id} is missing jobs", file=sys.stderr)
        return None
    result: list[Mapping[str, object]] = []
    for job in jobs:
        if isinstance(job, Mapping):
            result.append(job)
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Optional argument vector for tests.

    Returns:
        Parsed command-line namespace.

    """
    parser = argparse.ArgumentParser(
        description="Evaluate the Deploy Production red-run freeze.",
    )
    parser.add_argument(
        "--override",
        action="store_true",
        help="Owner bypass for the freeze (requires --reason).",
    )
    parser.add_argument(
        "--reason",
        default="",
        help="Logged explanation when --override is set.",
    )
    parser.add_argument(
        "--fetch-jobs",
        action="store_true",
        help="Load jobs for each run so gate-blocked runs can be skipped.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Read workflow-run JSON from stdin and print a freeze decision.

    Args:
        argv: Optional argument vector for tests.

    Returns:
        ``0`` when deploys/merges may proceed, ``1`` when frozen, ``2`` on
        invalid input.

    """
    args = parse_args(argv)
    try:
        payload = json.load(sys.stdin)
        decision = evaluate_freeze(
            payload,
            override=bool(args.override),
            reason=str(args.reason or ""),
            jobs_loader=fetch_run_jobs if args.fetch_jobs else None,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"invalid workflow-runs response: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(decision, sort_keys=True))
    print(str(decision["reason"]), file=sys.stderr)
    return 1 if decision["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

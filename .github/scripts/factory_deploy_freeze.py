#!/usr/bin/env python3
"""Decide whether Deploy Production and factory merges must freeze.

The freeze is active only while the most recent completed Deploy Production
run on ``main`` is red. Maintainers may bypass it with ``--override`` and a
non-empty ``--reason``. Factory merge drains have no override path.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping
from typing import TypedDict

WORKFLOW_NAME = "Deploy Production"
RED_CONCLUSIONS = frozenset({"failure", "timed_out", "startup_failure"})


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


def latest_completed_deploy_run(payload: object) -> Mapping[str, object] | None:
    """Return the newest completed Deploy Production run.

    Args:
        payload: Decoded, optionally paginated workflow-runs response.

    Returns:
        The latest completed run mapping, or ``None`` when none exist.

    """
    completed: dict[int, Mapping[str, object]] = {}
    for run in workflow_runs(payload):
        name = str(run.get("name") or "")
        status = str(run.get("status") or "").lower()
        if name and name != WORKFLOW_NAME:
            continue
        if status and status != "completed":
            continue
        completed[_run_id(run)] = run
    if not completed:
        return None

    def sort_key(item: tuple[int, Mapping[str, object]]) -> tuple[str, int]:
        run_id, run = item
        updated = str(run.get("updated_at") or run.get("created_at") or "")
        return (updated, run_id)

    return max(completed.items(), key=sort_key)[1]


def evaluate_freeze(
    payload: object,
    *,
    override: bool = False,
    reason: str = "",
) -> FreezeDecision:
    """Return the freeze decision for one workflow-runs payload.

    Args:
        payload: Decoded GitHub workflow-runs REST response.
        override: Whether a maintainer marked this run as the freeze bypass.
        reason: Required explanation when ``override`` is true.

    Returns:
        JSON-serializable decision including ``blocked``, ``frozen``, the
        blocking run URL when present, and a human-readable reason.

    """
    latest = latest_completed_deploy_run(payload)
    run_id = _run_id(latest) if latest is not None else None
    run_url = str((latest or {}).get("html_url") or "")
    conclusion = str((latest or {}).get("conclusion") or "").lower()
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
            "Maintainer override_freeze=true; proceeding despite a red "
            f"Deploy Production run ({run_url}). Reason: {stripped}"
            if last_is_red and run_url
            else f"Maintainer override_freeze=true. Reason: {stripped}"
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
            "reason": "no completed Deploy Production runs on main",
        }

    if last_is_red:
        why = (
            "Last completed Deploy Production run on main is "
            f"{conclusion}: {run_url or f'run {run_id}'}. "
            "Factory merges are frozen. Re-run Deploy Production with "
            "workflow_dispatch override_freeze=true and a reason after the fix "
            "is on main."
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
            f"Last completed Deploy Production run is {conclusion or 'success'}"
            + (f": {run_url}" if run_url else "")
        ),
    }


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
        help="Maintainer bypass for the freeze (requires --reason).",
    )
    parser.add_argument(
        "--reason",
        default="",
        help="Logged explanation when --override is set.",
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
        )
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"invalid workflow-runs response: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(decision, sort_keys=True))
    print(str(decision["reason"]), file=sys.stderr)
    return 1 if decision["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

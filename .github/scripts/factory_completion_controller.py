#!/usr/bin/env python3
"""Continuously drain ComicPile completion-stage PRs with healthy fixed workers."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

REPO = os.environ.get("GITHUB_REPOSITORY", "JoshCLWren/comic-pile")
GH_TIMEOUT_SECONDS = 120
REVIEW_BACKLOG_LIMIT = 15
HIGH_REVIEW_BACKLOG = 50
NORMAL_DRAIN_BATCH = 8
HIGH_DRAIN_BATCH = 12
RATE_LIMIT_COOLDOWN_SECONDS = 30 * 60
FAILURE_COOLDOWN_SECONDS = 15 * 60
MODEL_MISSING_COOLDOWN_SECONDS = 6 * 60 * 60
WORKER_RE = re.compile(r"(?m)^Worker:\s*opencode-free-model-factory-(?P<worker>\d+)\s*$")
OUTCOME_RE = re.compile(r"(?m)^Outcome:\s*(?P<outcome>.+?)\s*$")
ATTEMPT_OUTCOME_RE = re.compile(
    r"(?m)^Attempt outcome:\s*(?P<outcome>[a-z][a-z0-9_]+)\s*$"
)
UPDATED_RE = re.compile(r"(?m)^Updated:\s*(?P<updated>\S+)\s*$")
OWNER_RE = re.compile(r"^factory:(?P<worker>\d+)$")


def run_gh(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run one bounded GitHub CLI command."""
    try:
        proc = subprocess.run(
            ["gh", *args],
            text=True,
            capture_output=True,
            check=False,
            timeout=GH_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"gh {' '.join(args)} timed out") from exc
    if check and proc.returncode:
        raise RuntimeError(
            f"gh {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}"
        )
    return proc


def gh_json(args: list[str]) -> object | None:
    """Run GitHub CLI and decode its JSON output."""
    output = run_gh(args).stdout
    return json.loads(output) if output.strip() else None


def parse_time(value: str | None) -> int | None:
    """Parse an ISO timestamp to epoch seconds."""
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def review_capacity_worker(worker: str, *, review_backlog: int) -> bool:
    """Mirror the completion-pressure tiers used by factory_work_policy."""
    numeric = int(worker)
    if review_backlog >= 50:
        return numeric % 10 < 9
    if review_backlog >= 20:
        return numeric % 4 < 3
    if review_backlog >= 15:
        return numeric % 2 == 0
    return numeric % 4 == 2


def completion_batch_size(review_backlog: int) -> int:
    """Return bounded extra completion capacity for the current backlog."""
    if review_backlog < REVIEW_BACKLOG_LIMIT:
        return 0
    if review_backlog >= HIGH_REVIEW_BACKLOG:
        return HIGH_DRAIN_BATCH
    return NORMAL_DRAIN_BATCH


def cooldown_seconds(outcome: str | None) -> int:
    """Return how long a recently unhealthy worker should yield to healthy peers."""
    normalized = (outcome or "").strip().casefold()
    if normalized in {"model_unavailable", "model missing"} or "model missing" in normalized:
        return MODEL_MISSING_COOLDOWN_SECONDS
    if normalized in {"provider_unavailable", "rate limited"} or "rate limited" in normalized:
        return RATE_LIMIT_COOLDOWN_SECONDS
    if normalized in {
        "model_interruption",
        "worker_environment_failure",
        "control_plane_failure",
        "unknown_failure",
        "failure",
        "failed",
        "error",
    } or "failure" in normalized:
        return FAILURE_COOLDOWN_SECONDS
    return 0


def latest_worker_health(
    comments: Iterable[Mapping[str, Any]],
    *,
    trusted: Callable[[Mapping[str, Any]], bool] | None = None,
) -> dict[str, tuple[str, int]]:
    """Return the newest trusted heartbeat outcome for each fixed worker."""
    latest: dict[str, tuple[str, int]] = {}
    priorities: dict[str, int] = {}
    for comment in comments:
        if trusted is not None and not trusted(comment):
            continue
        body = str(comment.get("body") or "")
        worker_match = WORKER_RE.search(body)
        # Classified attempt evidence is authoritative for health. Legacy
        # heartbeat outcomes remain supported while existing records age out.
        attempt_match = ATTEMPT_OUTCOME_RE.search(body)
        outcome_match = attempt_match or OUTCOME_RE.search(body)
        updated_match = UPDATED_RE.search(body)
        if not worker_match or not outcome_match or not updated_match:
            continue
        updated = parse_time(updated_match.group("updated"))
        if updated is None:
            continue
        worker = worker_match.group("worker")
        priority = 1 if attempt_match else 0
        previous = latest.get(worker)
        previous_priority = priorities.get(worker, -1)
        if previous is None or priority > previous_priority or (
            priority == previous_priority and updated > previous[1]
        ):
            latest[worker] = (outcome_match.group("outcome").strip(), updated)
            priorities[worker] = priority
    return latest


def worker_is_cooling(
    worker: str,
    health: Mapping[str, tuple[str, int]],
    *,
    now_epoch: int,
) -> bool:
    """Return whether a worker is still inside a provider-failure cooldown."""
    status = health.get(worker)
    if status is None:
        return False
    outcome, updated = status
    cooldown = cooldown_seconds(outcome)
    return cooldown > 0 and now_epoch < updated + cooldown


def select_completion_workers(
    workers: Iterable[str],
    *,
    review_backlog: int,
    owned_workers: set[str] | None = None,
    health: Mapping[str, tuple[str, int]] | None = None,
    now_epoch: int | None = None,
) -> list[str]:
    """Select a bounded healthy batch, preferring review-capacity workers."""
    limit = completion_batch_size(review_backlog)
    if limit == 0:
        return []
    owned_workers = owned_workers or set()
    health = health or {}
    now_epoch = int(time.time()) if now_epoch is None else now_epoch
    eligible = [
        worker
        for worker in workers
        if worker not in owned_workers
        and not worker_is_cooling(worker, health, now_epoch=now_epoch)
    ]
    eligible.sort(
        key=lambda worker: (
            not review_capacity_worker(worker, review_backlog=review_backlog),
            int(worker),
        )
    )
    return eligible[:limit]


def flatten_pages(value: object | None) -> list[dict[str, Any]]:
    """Flatten gh api --paginate --slurp output."""
    result: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return result
    for page in value:
        if isinstance(page, list):
            result.extend(item for item in page if isinstance(item, dict))
        elif isinstance(page, dict):
            result.append(page)
    return result


def load_manifest_workers(path: Path) -> list[str]:
    """Read current configured worker IDs from the fixed-model manifest."""
    workers: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        worker = line.split("\t", 1)[0].strip()
        if worker.isdigit():
            workers.append(worker)
    return workers


def load_controller() -> Any:
    """Load the existing controller so lease and assignment semantics stay canonical."""
    scripts = Path(__file__).resolve().parent
    path = scripts / "factory-work-controller.py"
    spec = importlib.util.spec_from_file_location("factory_work_controller_for_completion", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load factory-work-controller.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_policy() -> Any:
    """Load canonical work policy helpers used for ranking and trust checks."""
    scripts = Path(__file__).resolve().parent
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import factory_work_policy as policy

    return policy


def registry_comments() -> list[dict[str, Any]]:
    """Fetch the heartbeat registry once for health-aware batch selection."""
    pages = gh_json(
        [
            "api",
            "--paginate",
            "--slurp",
            f"repos/{REPO}/issues/1093/comments?per_page=100",
        ]
    )
    return flatten_pages(pages)


def owned_worker_ids(items: Iterable[Mapping[str, Any]]) -> set[str]:
    """Return workers that already hold a lease in the supplied snapshot."""
    workers: set[str] = set()
    for item in items:
        for label in item.get("labels") or []:
            name = label.get("name") if isinstance(label, Mapping) else label
            match = OWNER_RE.fullmatch(str(name or ""))
            if match:
                workers.add(match.group("worker"))
    return workers


def assign_completion_batch(*, now_epoch: int | None = None) -> dict[str, object]:
    """Claim one bounded batch of existing completion-stage PRs."""
    now_epoch = int(time.time()) if now_epoch is None else now_epoch
    controller = load_controller()
    policy = load_policy()

    controller.reconcile_stale_leases(now_epoch=now_epoch)
    issues = controller.list_issues()
    prs = controller.list_prs()
    backlog = policy.factory_review_backlog_count(prs)
    if backlog < REVIEW_BACKLOG_LIMIT:
        return {"backlog": backlog, "selected_workers": [], "assignments": []}

    manifest = Path(__file__).resolve().parents[1] / "free-model-factories.tsv"
    workers = load_manifest_workers(manifest)
    owned = owned_worker_ids([*issues, *prs])
    try:
        comments = registry_comments()
        health = latest_worker_health(comments, trusted=policy.comment_is_trusted)
    except RuntimeError as exc:
        print(
            f"[factory-completion] heartbeat health unavailable; dispatching without cooldowns: {exc}",
            file=sys.stderr,
        )
        health = {}

    selected = select_completion_workers(
        workers,
        review_backlog=backlog,
        owned_workers=owned,
        health=health,
        now_epoch=now_epoch,
    )

    try:
        retry_counts: dict[int, int] | None = controller.load_no_diff_attempts(now_epoch)
    except RuntimeError as exc:
        retry_counts = None
        print(
            f"[factory-completion] no-diff history unavailable; PR completion remains safe: {exc}",
            file=sys.stderr,
        )
    candidates = policy.build_candidates(
        issues,
        prs,
        no_diff_attempts_by_issue=retry_counts or {},
    )
    # This controller is deliberately completion-only. It must never manufacture
    # fresh issue work, even when a regular dispatcher tick is delayed.
    remaining = [candidate for candidate in candidates if candidate.kind == "pr"]

    assignments: list[dict[str, object]] = []
    for worker in selected:
        # Recheck the worker lease at the mutation boundary. The regular
        # dispatcher and the completion drain have independent workflow
        # concurrency groups, so a worker can become busy after our snapshot.
        if controller.worker_has_active_lease(worker):
            continue
        ordered = policy.order_candidates_for_worker(remaining, worker)
        for candidate in ordered:
            if not controller.candidate_is_live_executable(candidate):
                continue
            if not controller.assign_candidate(candidate, worker):
                continue
            assignments.append(
                {
                    "worker": worker,
                    "number": candidate.number,
                    "stage": candidate.stage,
                    "conflicted": candidate.conflicted,
                }
            )
            remaining = [item for item in remaining if item.number != candidate.number]
            break

    return {
        "backlog": backlog,
        "selected_workers": selected,
        "assignments": assignments,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--now-epoch", type=int)
    args = parser.parse_args()
    print(json.dumps(assign_completion_batch(now_epoch=args.now_epoch), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

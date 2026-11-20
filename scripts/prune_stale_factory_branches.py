#!/usr/bin/env python3
"""Prune stale factory/local/backup remote branches (dry-run by default).

Safety-first cleanup for Comic Pile factory branch hygiene.
This script never deletes branches with open PRs or live local worktrees, and it
protects default/protected/release refs, active factory leases, checkpoint
handoff branches, and branches whose safety cannot be proven. It defaults to
dry-run/report mode and only deletes when --apply is explicitly requested.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

STALE_BRANCH_PREFIXES = ("factory/", "local-factory/", "local/", "backup/")
RELEASE_PREFIX = "release/"
CHECKPOINT_PREFIX = "factory/work-checkpoints/"
DEFAULT_AGE_DAYS = 14
# Written by .github/scripts/factory_no_progress_retirement.py onto the linked
# issue when an attempt is retired. Policy says "Never delete the branch" for
# retired work, so a branch linked to such an issue is kept out of cleanup.
RETIRE_MARKER = "comic-pile-factory-no-progress-retired-v1"


def _positive_int_env(name: str, default: int) -> int:
    """Return a positive integer env setting or a safe default."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


# Match shared factory policy defaults: local leases default to 24h and are
# stale only when there is verified inactivity older than the TTL. Unknown
# activity must be treated as active (fail closed). Invalid/non-positive values
# must not weaken lease protection.
LOCAL_LEASE_TTL = timedelta(
    seconds=_positive_int_env("FACTORY_LOCAL_LEASE_TTL_SECONDS", 86400)
)
NUMBERED_LEASE_RECENT_ACTIVITY = timedelta(minutes=15)

ISSUE_PATTERNS = (
    re.compile(r"(?:^|/)i(?P<issue>\d+)(?:$|[^0-9])"),
    re.compile(r"factory/(?:[0-9]+-)?(?P<issue>\d+)-"),
    re.compile(r"factory/work-checkpoints/issue-(?P<issue>\d+)/"),
    re.compile(r"issue[-/](?P<issue>\d+)"),
    re.compile(r"^local/(?P<issue>\d{3,6})(?:[-_]|$)"),
    re.compile(r"^local/acp-(?P<issue>\d{3,6})(?:[-_]|$)"),
    re.compile(r"^local/(?:fix|task|issue|pr)[-_]?(?P<issue>\d{3,6})(?:[-_]|$)"),
)
OWNER_RE = re.compile(r"^factory:(?:local|[1-9][0-9]*)$")
ACTIVE_STAGE_LABELS = {
    "factory:building",
    "factory:review",
    "factory:changes-requested",
    "factory:ci",
    "factory:ready",
    "factory:blocked",
}


@dataclass(frozen=True)
class BranchInfo:
    """Remote branch metadata needed for pruning decisions."""

    name: str
    sha: str
    committed_at: datetime
    protected: bool = False


@dataclass(frozen=True)
class LeaseSignal:
    """Observed factory ownership/lease signal for a linked target."""

    target: str
    state: str
    owner: str | None
    labels: frozenset[str]
    updated_at: datetime | None
    has_open_pr: bool = False
    is_draft_handoff_pr: bool = False


@dataclass(frozen=True)
class Decision:
    """Pruning decision for one branch."""

    branch: str
    sha: str
    action: str  # delete | skip
    reasons: tuple[str, ...]
    category: str
    age_days: float
    merged: bool
    open_pr: bool
    linked_issue: int | None = None

    @property
    def eligible(self) -> bool:
        """Return whether this branch is eligible for deletion."""
        return self.action == "delete"


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(UTC)


def parse_iso8601(value: str) -> datetime | None:
    """Parse an ISO-8601 timestamp into UTC."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def run(cmd: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a subprocess command and return its result."""
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr.strip()}"
        )
    return proc


def is_stale_scope_branch(name: str) -> bool:
    """Return whether the branch is in factory/local/backup cleanup scope."""
    return any(name.startswith(prefix) for prefix in STALE_BRANCH_PREFIXES)


def linked_issue_number(branch_name: str) -> int | None:
    """Extract a linked issue number from a branch name, if present."""
    for pattern in ISSUE_PATTERNS:
        match = pattern.search(branch_name)
        if match:
            return int(match.group("issue"))
    return None


def is_default_or_release_branch(name: str, default_branch: str) -> bool:
    """Return whether the branch is a default or release ref."""
    return name in {default_branch, "main", "master", "HEAD"} or name.startswith(RELEASE_PREFIX)


def local_worktree_branches(repo_root: Path) -> set[str]:
    """Return branch names checked out in local git worktrees."""
    proc = run(["git", "-C", str(repo_root), "worktree", "list", "--porcelain"])
    branches: set[str] = set()
    for line in proc.stdout.splitlines():
        if line.startswith("branch refs/heads/"):
            branches.add(line.removeprefix("branch refs/heads/").strip())
    return branches


def remote_default_branch(repo_root: Path, remote: str = "origin") -> str:
    """Resolve the default branch for a remote."""
    proc = run(["git", "-C", str(repo_root), "symbolic-ref", f"refs/remotes/{remote}/HEAD"], check=False)
    if proc.returncode == 0:
        ref = proc.stdout.strip()
        prefix = f"refs/remotes/{remote}/"
        if ref.startswith(prefix):
            return ref[len(prefix):]
    for candidate in ("main", "master"):
        if run(["git", "-C", str(repo_root), "rev-parse", "--verify", f"{remote}/{candidate}"], check=False).returncode == 0:
            return candidate
    return "main"


def list_remote_branches(repo_root: Path, remote: str = "origin") -> list[BranchInfo]:
    """List remote branches with commit metadata."""
    fmt = "%(refname:short)\t%(objectname)\t%(committerdate:iso-strict)"
    proc = run(["git", "-C", str(repo_root), "for-each-ref", f"refs/remotes/{remote}", f"--format={fmt}"])
    branches: list[BranchInfo] = []
    prefix = f"{remote}/"
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        ref, sha, committed = line.split("\t", 2)
        if not ref.startswith(prefix) or ref == f"{remote}/HEAD":
            continue
        name = ref[len(prefix):]
        committed_at = parse_iso8601(committed)
        if committed_at is None:
            committed_at = datetime.fromtimestamp(0, tz=UTC)
        branches.append(BranchInfo(name=name, sha=sha, committed_at=committed_at))
    return branches


def is_ancestor(repo_root: Path, ancestor_ref: str, descendant_ref: str) -> bool:
    """Return whether ancestor_ref is an ancestor of descendant_ref."""
    proc = run(
        [
            "git",
            "-C",
            str(repo_root),
            "merge-base",
            "--is-ancestor",
            ancestor_ref,
            descendant_ref,
        ],
        check=False,
    )
    return proc.returncode == 0


def normalize_repo_slug(value: str) -> str:
    """Normalize a GitHub repository slug for comparison.

    Args:
        value: Repository identifier as owner/name or a git/https URL.

    Returns:
        Normalized ``owner/name`` slug in lowercase without a trailing ``.git``.
    """
    slug = value.strip().removesuffix(".git").strip("/")
    if slug.startswith(("http://", "https://", "ssh://", "git@")):
        slug = slug.replace(":", "/")
        parts = [part for part in slug.split("/") if part]
        if len(parts) >= 2:
            slug = f"{parts[-2]}/{parts[-1]}"
    return slug.lower()


def remote_github_repo(repo_root: Path, remote: str) -> str | None:
    """Resolve the GitHub repository targeted by a git remote.

    Args:
        repo_root: Repository root containing the git remote configuration.
        remote: Git remote name to inspect.

    Returns:
        Normalized ``owner/name`` slug, or ``None`` when it cannot be resolved.
    """
    proc = run(["git", "-C", str(repo_root), "remote", "get-url", remote], check=False)
    if proc.returncode != 0:
        return None
    slug = normalize_repo_slug(proc.stdout.strip())
    if "/" not in slug or slug.count("/") != 1:
        return None
    owner, name = slug.split("/", 1)
    if not owner or not name:
        return None
    return slug


def fetch_pr_records(repo: str, branch_name: str | None = None) -> dict[str, list[dict[str, object]]]:
    """Fetch the complete open+closed PR history grouped by branch name.

    If branch_name is provided, only fetch PRs for that specific branch to save
    API quota and time during deletion checks.

    Raises on lookup failure so cleanup cannot proceed with incomplete safety
    data. Pagination is followed to completion: a capped list would let an old
    open PR fall outside the result and lose its protection. Normalized records
    carry ``state``, ``mergedAt`` and ``closedAt`` so the post-merge/abandonment
    wait is measured from the real event rather than from the last commit.
    """
    if branch_name:
        # Fetch only PRs for the specific branch to avoid re-reading the entire repo.
        # We use the search API or filtering to be efficient.
        proc = run([
            "gh", "api", "--paginate", "--slurp",
            f"repos/{repo}/pulls?state=all&per_page=100&head={branch_name}"
        ], check=False)
    else:
        proc = run([
            "gh", "api", "--paginate", "--slurp",
            f"repos/{repo}/pulls?state=all&per_page=100",
        ], check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"unable to list PRs: {proc.stderr.strip() or proc.stdout.strip()}")
    try:
        pages = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"unable to parse PR list: {exc}") from exc
    if not isinstance(pages, list):
        raise RuntimeError("PR list response was not a list")
    by_head: dict[str, list[dict[str, object]]] = {}
    for page in pages:
        if not isinstance(page, list):
            raise RuntimeError("PR list page was not a list")
        for pr in page:
            if not isinstance(pr, dict):
                raise RuntimeError("PR list contained a non-object entry")
            head_obj = pr.get("head")
            ref = head_obj.get("ref") if isinstance(head_obj, dict) else None
            head = ref if isinstance(ref, str) else ""
            if not head:
                continue
            record: dict[str, object] = {
                "number": pr.get("number"),
                "headRefName": head,
                "state": str(pr.get("state") or "OPEN").upper(),
                "isDraft": bool(pr.get("draft")),
                "mergedAt": pr.get("merged_at"),
                "closedAt": pr.get("closed_at"),
                "updatedAt": pr.get("updated_at"),
                "labels": pr.get("labels") or [],
                "title": pr.get("title"),
                "url": pr.get("html_url"),
            }
            by_head.setdefault(head, []).append(record)
    return by_head



def fetch_protected_branches(repo: str) -> set[str]:
    """Fetch protected branch names from GitHub.

    Raises on lookup failure so cleanup cannot proceed with incomplete safety data.
    """
    proc = run([
        "gh", "api", f"repos/{repo}/branches?protected=true&per_page=100", "--paginate", "--slurp",
    ], check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"unable to list protected branches: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    try:
        pages = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"unable to parse protected branch list: {exc}") from exc
    if not isinstance(pages, list):
        raise RuntimeError("protected branch response was not a list")
    protected: set[str] = set()
    for page in pages:
        if not isinstance(page, list):
            raise RuntimeError("protected branch page was not a list")
        for item in page:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if isinstance(name, str):
                protected.add(name)
    return protected


def fetch_issue_signal(repo: str, issue_number: int) -> LeaseSignal | None:
    """Fetch lease-relevant issue metadata from GitHub.

    Returns None for a missing issue. Raises on other lookup failures.
    """
    proc = run(["gh", "api", f"repos/{repo}/issues/{issue_number}"], check=False)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        if "404" in detail or "Not Found" in detail:
            return None
        raise RuntimeError(f"unable to fetch issue #{issue_number}: {detail}")
    try:
        issue = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"unable to parse issue #{issue_number}: {exc}") from exc
    if not isinstance(issue, dict):
        raise RuntimeError(f"issue #{issue_number} response was not an object")
    labels = {
        str(label.get("name"))
        for label in (issue.get("labels") or [])
        if isinstance(label, dict) and label.get("name")
    }
    owners = sorted(label for label in labels if OWNER_RE.fullmatch(label) and label != "factory:unowned")
    owner = owners[0] if len(owners) == 1 else (owners[0] if owners else None)
    updated_at = parse_iso8601(str(issue.get("updated_at") or issue.get("updatedAt") or ""))
    return LeaseSignal(
        target=f"issue:{issue_number}",
        state=str(issue.get("state") or ""),
        owner=owner,
        labels=frozenset(labels),
        updated_at=updated_at,
        has_open_pr=bool(issue.get("pull_request")),
    )


def fetch_issue_retired(repo: str, issue_number: int) -> bool:
    """Return whether an issue carries a no-progress retirement marker.

    Raises on lookup failure so cleanup fails closed: a branch tied to a
    retired attempt must never be deleted, and an unreadable comment list must
    not be treated as "not retired".
    """
    proc = run([
        "gh", "api", f"repos/{repo}/issues/{issue_number}/comments?per_page=100",
        "--paginate", "--slurp",
    ], check=False)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"unable to read comments for issue #{issue_number}: {detail}")
    try:
        pages = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"unable to parse comments for issue #{issue_number}: {exc}") from exc
    if not isinstance(pages, list):
        raise RuntimeError(f"issue #{issue_number} comments response was not a list")
    for page in pages:
        if not isinstance(page, list):
            raise RuntimeError(f"issue #{issue_number} comments page was not a list")
        for comment in page:
            body = comment.get("body") if isinstance(comment, dict) else None
            if isinstance(body, str) and RETIRE_MARKER in body:
                return True
    return False


def active_lease(signal: LeaseSignal | None, now: datetime) -> tuple[bool, str | None]:
    """Return whether a linked target has an active, unexpired factory lease."""
    if signal is None:
        return False, None
    owner = signal.owner
    if owner is None:
        # Multiple owners or no owner: multiple means ambiguous/unsafe.
        owners = sorted(
            label for label in signal.labels if OWNER_RE.fullmatch(label) and label != "factory:unowned"
        )
        if len(owners) > 1:
            return True, f"ambiguous active owners on {signal.target}"
        return False, None
    if signal.state.lower() == "closed":
        return False, None
    updated = signal.updated_at
    if owner == "factory:local":
        # Shared policy: a local lease is stale only with verified inactivity
        # older than the TTL. Unknown activity cannot prove inactivity.
        if updated is None or now - updated <= LOCAL_LEASE_TTL:
            return True, f"active local lease on {signal.target}"
        return False, None
    # Numbered fixed-model lease: verified inactivity requires evidence of no
    # active workflow run; without that evidence, treat present owner as active.
    # Recent activity is always active.
    if updated is None or now - updated <= NUMBERED_LEASE_RECENT_ACTIVITY:
        return True, f"active numbered lease on {signal.target}"
    # Cannot prove no active workflow run from branch/issue metadata alone.
    return True, f"cannot verify numbered lease expiry on {signal.target}"


def unexpired_handoff(
    branch: BranchInfo, linked_signal: LeaseSignal | None, now: datetime
) -> tuple[bool, str | None]:
    """Return whether a branch represents a protected handoff/checkpoint.

    Checkpoint branches are persisted recovery refs. Safe retirement requires
    explicit incorporation and ownership/hold proof; this cleanup script cannot
    prove that, so checkpoint branches are never auto-deleted.
    """
    if not branch.name.startswith(CHECKPOINT_PREFIX):
        return False, None
    return True, "checkpoint branch requires explicit incorporated-retirement proof"


def _pr_state(pr: Mapping[str, object]) -> str:
    """Return a normalized PR state, defaulting to OPEN when absent."""
    return str(pr.get("state") or "OPEN").upper()


def _waiting_period_start(
    branch: BranchInfo, prs: Sequence[Mapping[str, object]]
) -> datetime | None:
    """Return the date from which the post-merge/abandonment wait begins.

    - A settled PR (MERGED/CLOSED) starts the clock at its merge/close event.
    - A settled PR with no parseable date yields None (fail closed).
    - A branch with no PR history uses its last commit as the abandonment
      proxy; there is no PR event to measure from.
    """
    settled = [pr for pr in prs if _pr_state(pr) != "OPEN"]
    settled_dates: list[datetime] = []
    for pr in settled:
        for key in ("mergedAt", "merged_at", "closedAt", "closed_at"):
            value = pr.get(key)
            if isinstance(value, str):
                parsed = parse_iso8601(value)
            elif isinstance(value, datetime):
                parsed = value
            else:
                parsed = None
            if parsed is not None:
                settled_dates.append(parsed)
                break
    if settled and not settled_dates:
        return None
    if settled_dates:
        return max(settled_dates)
    return branch.committed_at


def evaluate_branch(
    branch: BranchInfo,
    *,
    default_branch: str,
    protected_names: set[str],
    pr_records: Mapping[str, Sequence[Mapping[str, object]]],
    live_worktree_refs: set[str],
    now: datetime,
    age_days: int,
    is_merged: Callable[[BranchInfo], bool],
    lease_lookup: Callable[[int], LeaseSignal | None],
    retirement_lookup: Callable[[int], bool],
) -> Decision:
    """Evaluate one branch and return a pruning decision."""
    age = (now - branch.committed_at).total_seconds() / 86400.0
    issue = linked_issue_number(branch.name)
    prs = list(pr_records.get(branch.name, ()))
    open_pr = any(_pr_state(pr) == "OPEN" for pr in prs)
    category = "factory/local/backup" if is_stale_scope_branch(branch.name) else "other"

    reasons: list[str] = []
    if branch.name in protected_names or branch.protected:
        reasons.append("protected branch")
    if is_default_or_release_branch(branch.name, default_branch):
        reasons.append("default or release ref")
    if open_pr:
        reasons.append("open PR exists")
    if branch.name in live_worktree_refs:
        reasons.append("checked out in live local worktree")
    if not is_stale_scope_branch(branch.name):
        reasons.append("outside factory/local/backup scope")

    leased = False
    retired = False
    signal: LeaseSignal | None = None
    if issue is not None:
        try:
            signal = lease_lookup(issue)
        except Exception as exc:
            reasons.append(f"unable to verify lease state: {exc}")
        else:
            leased, lease_reason = active_lease(signal, now)
            if leased and lease_reason:
                reasons.append(lease_reason)
        try:
            retired = retirement_lookup(issue)
        except Exception as exc:
            reasons.append(f"unable to verify retirement state: {exc}")
        if retired:
            reasons.append("preserved by no-progress retirement; policy forbids deletion")

    handoff_blocked, handoff_reason = unexpired_handoff(branch, signal, now)
    if handoff_blocked and handoff_reason:
        reasons.append(handoff_reason)

    merged = False
    if is_stale_scope_branch(branch.name):
        try:
            merged = is_merged(branch)
        except Exception as exc:
            reasons.append(f"unable to verify merged state: {exc}")

    # The >14-day waiting period starts at the PR merge/close event, not at the
    # last commit. A branch whose PR closed today is not abandonable today even
    # when its last commit is a month old. If a settled PR has no usable date,
    # the waiting period cannot be established and the branch is kept.
    waiting_since = _waiting_period_start(branch, prs)
    if waiting_since is None:
        reasons.append("waiting period since merge/abandonment cannot be established")
    else:
        wait_days = (now - waiting_since).total_seconds() / 86400.0
        if wait_days < age_days:
            reasons.append(
                f"waiting period since merge/abandonment not met ({wait_days:.1f}d < {age_days}d)"
            )

    if age < age_days:
        reasons.append(f"younger than {age_days} days")

    # Eligible only when scope matches, no hard protection applies, the branch
    # is old enough, and the post-merge/abandonment wait is established/elapsed.
    hard_protections = (
        any(
            r in reasons
            for r in (
                "protected branch",
                "default or release ref",
                "open PR exists",
                "checked out in live local worktree",
                "outside factory/local/backup scope",
                "preserved by no-progress retirement; policy forbids deletion",
                "waiting period since merge/abandonment cannot be established",
            )
        )
        or leased
        or retired
        or handoff_blocked
        or any(
            r.startswith("waiting period since merge/abandonment not met")
            or r.startswith("unable to verify")
            for r in reasons
        )
    )

    stale_enough = age >= age_days
    eligible = (not hard_protections) and stale_enough and waiting_since is not None
    if eligible:
        wait_days = (now - waiting_since).total_seconds() / 86400.0
        return Decision(
            branch=branch.name,
            sha=branch.sha,
            action="delete",
            reasons=(
                f"eligible: {'merged' if merged else 'abandoned'}; "
                f"commit age {age:.1f}d, wait since merge/abandonment {wait_days:.1f}d",
            ),
            category=category,
            age_days=round(age, 2),
            merged=merged,
            open_pr=open_pr,
            linked_issue=issue,
        )

    # Normalize skip reasons: keep the most relevant ones.
    filtered = [r for r in reasons if r not in ("age threshold met and branch is not merged",)]
    if not filtered:
        filtered = ["not eligible"]
    return Decision(
        branch=branch.name,
        sha=branch.sha,
        action="skip",
        reasons=tuple(dict.fromkeys(filtered)),
        category=category,
        age_days=round(age, 2),
        merged=merged,
        open_pr=open_pr,
        linked_issue=issue,
    )


def remote_branch_sha(repo_root: Path, remote: str, branch: str) -> str | None:
    """Return the current remote head SHA for a branch, or None if missing."""
    proc = run(
        ["git", "-C", str(repo_root), "ls-remote", "--heads", remote, f"refs/heads/{branch}"],
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"unable to read remote branch {remote}/{branch}: {proc.stderr.strip()}")
    line = proc.stdout.strip().splitlines()
    if not line:
        return None
    return line[0].split()[0]


def delete_remote_branch(repo_root: Path, remote: str, branch: str, expected_sha: str) -> None:
    """Delete a remote branch only if its current head matches the evaluated SHA."""
    current = remote_branch_sha(repo_root, remote, branch)
    if current is None:
        raise RuntimeError(f"remote branch {remote}/{branch} no longer exists")
    if current != expected_sha:
        raise RuntimeError(
            f"remote branch {remote}/{branch} changed since evaluation "
            f"(expected {expected_sha}, found {current})"
        )
    run(["git", "-C", str(repo_root), "push", remote, "--delete", branch])


def render_report(
    decisions: list[Decision],
    *,
    mode: str,
    now: datetime,
    remote: str,
    age_days: int,
) -> str:
    """Render a human-readable prune report.

    Args:
        decisions: Evaluated branch decisions to include in the report.
        mode: Report mode label, such as dry-run or apply.
        now: Timestamp used for report generation.
        remote: Remote name whose branches were evaluated.
        age_days: Minimum age threshold in days.

    Returns:
        A Markdown-formatted report string.
    """
    delete = [d for d in decisions if d.eligible]
    skip = [d for d in decisions if not d.eligible]
    lines = [
        f"# Branch prune {mode} report",
        "",
        f"- Generated: {now.isoformat()}",
        f"- Remote: `{remote}`",
        f"- Age threshold: {age_days} days",
        f"- Eligible for deletion: {len(delete)}",
        f"- Skipped/protected: {len(skip)}",
        "",
        "## Eligible branches",
    ]
    if delete:
        for d in sorted(delete, key=lambda x: x.branch):
            state = "merged" if d.merged else "abandoned"
            issue = d.linked_issue if d.linked_issue is not None else "n/a"
            reasons = "; ".join(d.reasons)
            lines.append(
                f"- `{d.branch}` — {state}, age={d.age_days}d, "
                f"issue={issue}; {reasons}"
            )
    else:
        lines.append("- (none)")
    lines.extend(["", "## Skipped branches"])
    for d in sorted(skip, key=lambda x: x.branch):
        state = "merged" if d.merged else "not merged"
        issue = d.linked_issue if d.linked_issue is not None else "n/a"
        reasons = "; ".join(d.reasons)
        lines.append(
            f"- `{d.branch}` — {state}, age={d.age_days}d, "
            f"open_pr={str(d.open_pr).lower()}, issue={issue}; {reasons}"
        )
    lines.append("")
    return "\n".join(lines)


def decide_branches(
    branches: Iterable[BranchInfo],
    *,
    default_branch: str,
    protected_names: set[str],
    pr_records: Mapping[str, Sequence[Mapping[str, object]]],
    live_worktree_refs: set[str],
    now: datetime,
    age_days: int = DEFAULT_AGE_DAYS,
    is_merged: Callable[[BranchInfo], bool],
    lease_lookup: Callable[[int], LeaseSignal | None],
    retirement_lookup: Callable[[int], bool],
) -> list[Decision]:
    """Evaluate all branches and return pruning decisions.

    Args:
        branches: Remote branches to evaluate.
        default_branch: Resolved default branch name for the remote.
        protected_names: Branch names protected by policy or GitHub settings.
        pr_records: Pull request records grouped by head branch name.
        live_worktree_refs: Local branch refs checked out in live worktrees.
        now: Current timestamp for age and lease calculations.
        age_days: Minimum age threshold in days.
        is_merged: Predicate that reports whether a branch is merged.
        lease_lookup: Callable returning lease state for a linked issue.
        retirement_lookup: Callable returning retirement state for an issue.

    Returns:
        A list of pruning decisions in input order.
    """
    return [
        evaluate_branch(
            branch,
            default_branch=default_branch,
            protected_names=protected_names,
            pr_records=pr_records,
            live_worktree_refs=live_worktree_refs,
            now=now,
            age_days=age_days,
            is_merged=is_merged,
            lease_lookup=lease_lookup,
            retirement_lookup=retirement_lookup,
        )
        for branch in branches
    ]


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser.

    Returns:
        Configured argument parser for the pruning command.
    """
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", help="GitHub repo (owner/name) for PR/issue/protection lookups")
    p.add_argument("--remote", default="origin", help="Git remote to inspect (default: origin)")
    p.add_argument("--age-days", type=int, default=DEFAULT_AGE_DAYS, help="Minimum age in days (default: 14)")
    p.add_argument("--apply", action="store_true", help="Delete eligible remote branches (default: dry-run)")
    p.add_argument("--format", choices=("text", "json"), default="text", help="Report format")
    p.add_argument("--report-file", help="Write report output to this file")
    p.add_argument("--all-branches", action="store_true", help="Evaluate all remote branches, not just factory/local/backup scope")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    """Run the stale branch pruning command.

    Args:
        argv: Optional command-line arguments. Defaults to process arguments.

    Returns:
        Process exit code: 0 on success, 1 when apply-time deletions fail.
    """
    args = build_parser().parse_args(argv)
    if not args.repo:
        raise SystemExit(
            "error: --repo is required so open PR, protection, and lease safety checks "
            "cannot be bypassed"
        )

    repo_root = Path.cwd()
    remote = args.remote
    remote_repo = remote_github_repo(repo_root, remote)
    if remote_repo is None:
        raise SystemExit(
            f"error: unable to resolve GitHub repository for remote '{remote}'; "
            "cannot verify --repo matches the remote being deleted from"
        )
    expected_repo = normalize_repo_slug(args.repo)
    if remote_repo != expected_repo:
        raise SystemExit(
            f"error: --repo {args.repo} resolves to '{expected_repo}' but remote "
            f"'{remote}' targets '{remote_repo}'; refusing to continue"
        )

    now = utc_now()
    default_branch = remote_default_branch(repo_root, remote)

    # Refresh remote-tracking refs before building the inventory so dry-run and
    # apply decisions are made against current remote state.
    fetch_proc = run(["git", "-C", str(repo_root), "fetch", remote, "--prune"], check=False)
    if fetch_proc.returncode != 0:
        raise SystemExit(
            f"error: unable to refresh remote refs: {fetch_proc.stderr.strip() or fetch_proc.stdout.strip()}"
        )

    branches = list_remote_branches(repo_root, remote)
    if not args.all_branches:
        branches = [b for b in branches if is_stale_scope_branch(b.name)]

    # Fail closed: complete, successful safety lookups are required before any
    # branch can be reported deletable or deleted.
    protected = fetch_protected_branches(args.repo)
    protected.update({default_branch, "main", "master", "gh-pages"})
    pr_records = fetch_pr_records(args.repo)
    live_refs = local_worktree_branches(repo_root)

    lease_cache: dict[int, LeaseSignal | None] = {}

    def lease_lookup(issue_number: int) -> LeaseSignal | None:
        if issue_number in lease_cache:
            return lease_cache[issue_number]
        lease_cache[issue_number] = fetch_issue_signal(args.repo, issue_number)
        return lease_cache[issue_number]

    retirement_cache: dict[int, bool] = {}

    def retirement_lookup(issue_number: int) -> bool:
        if issue_number not in retirement_cache:
            retirement_cache[issue_number] = fetch_issue_retired(args.repo, issue_number)
        return retirement_cache[issue_number]

    def is_merged(branch: BranchInfo) -> bool:
        return is_ancestor(repo_root, f"{remote}/{branch.name}", f"{remote}/{default_branch}")

    decisions = decide_branches(
        branches,
        default_branch=default_branch,
        protected_names=protected,
        pr_records=pr_records,
        live_worktree_refs=live_refs,
        now=now,
        age_days=args.age_days,
        is_merged=is_merged,
        lease_lookup=lease_lookup,
        retirement_lookup=retirement_lookup,
    )

    mode = "apply" if args.apply else "dry-run"
    if args.format == "json":
        payload = {
            "mode": mode,
            "generated_at": now.isoformat(),
            "remote": remote,
            "age_days": args.age_days,
            "decisions": [
                {
                    "branch": d.branch,
                    "sha": d.sha,
                    "action": d.action,
                    "eligible": d.eligible,
                    "reasons": list(d.reasons),
                    "category": d.category,
                    "age_days": d.age_days,
                    "merged": d.merged,
                    "open_pr": d.open_pr,
                    "linked_issue": d.linked_issue,
                }
                for d in decisions
            ],
        }
        report = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    else:
        report = render_report(decisions, mode=mode, now=now, remote=remote, age_days=args.age_days)

    if args.report_file:
        report_path = Path(args.report_file)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")

    sys.stdout.write(report)

    deleted = 0
    failures: list[str] = []
    if args.apply:
        for decision in decisions:
            if not decision.eligible:
                continue
            try:
                # Refresh remote-tracking refs and all safety checks immediately
                # before deletion so protections that appeared during the
                # inventory walk are honored even when the branch SHA is unchanged.
                fetch_proc = run(
                    ["git", "-C", str(repo_root), "fetch", remote, "--prune"],
                    check=False,
                )
                if fetch_proc.returncode != 0:
                    raise RuntimeError(
                        "unable to refresh remote refs before delete: "
                        f"{fetch_proc.stderr.strip() or fetch_proc.stdout.strip()}"
                    )

                fresh_branches = {
                    b.name: b for b in list_remote_branches(repo_root, remote)
                }
                fresh_branch = fresh_branches.get(decision.branch)
                if fresh_branch is None:
                    print(
                        f"SKIPPED {decision.branch}: remote branch no longer exists",
                        file=sys.stderr,
                    )
                    continue

                fresh_protected = fetch_protected_branches(args.repo)
                fresh_protected.update({default_branch, "main", "master", "gh-pages"})
                fresh_pr_records = fetch_pr_records(args.repo)
                fresh_live_refs = local_worktree_branches(repo_root)

                def fresh_lease_lookup(issue_number: int) -> LeaseSignal | None:
                    return fetch_issue_signal(args.repo, issue_number)

                def fresh_retirement_lookup(issue_number: int) -> bool:
                    return fetch_issue_retired(args.repo, issue_number)

                fresh_decision = evaluate_branch(
                    fresh_branch,
                    default_branch=default_branch,
                    protected_names=fresh_protected,
                    pr_records=fresh_pr_records,
                    live_worktree_refs=fresh_live_refs,
                    now=utc_now(),
                    age_days=args.age_days,
                    is_merged=is_merged,
                    lease_lookup=fresh_lease_lookup,
                    retirement_lookup=fresh_retirement_lookup,
                )
                if not fresh_decision.eligible:
                    print(
                        f"SKIPPED {decision.branch}: protection appeared before delete; "
                        f"{'; '.join(fresh_decision.reasons)}",
                        file=sys.stderr,
                    )
                    continue

                delete_remote_branch(
                    repo_root, remote, decision.branch, fresh_decision.sha
                )
                deleted += 1
                print(f"DELETED {remote}/{decision.branch}", file=sys.stderr)
            except Exception as exc:
                failures.append(f"{decision.branch}: {exc}")
                print(f"FAILED {decision.branch}: {exc}", file=sys.stderr)

    if args.apply:
        print(f"Applied deletions: {deleted}; failures: {len(failures)}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

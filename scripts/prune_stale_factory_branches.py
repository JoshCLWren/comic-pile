#!/usr/bin/env python3
"""Prune stale factory/local/backup remote branches (dry-run by default).

Safety-first cleanup for Comic Pile factory branch hygiene.
This script never deletes branches with open PRs or live local worktrees, and it
protects default/protected/release refs, active factory leases, and unexpired
handoffs. It defaults to dry-run/report mode and only deletes when --apply is
explicitly requested.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, UTC
from pathlib import Path
from typing import Any
from collections.abc import Callable, Iterable, Mapping, Sequence

STALE_BRANCH_PREFIXES = ("factory/", "local-factory/", "local/", "backup/")
RELEASE_PREFIX = "release/"
CHECKPOINT_PREFIX = "factory/work-checkpoints/"
DEFAULT_AGE_DAYS = 14
LOCAL_LEASE_TTL = timedelta(minutes=60)
NUMBERED_LEASE_RECENT_ACTIVITY = timedelta(minutes=15)

ISSUE_PATTERNS = (
    re.compile(r"(?:^|/)i(?P<issue>\d+)(?:$|[^0-9])"),
    re.compile(r"factory/(?:[0-9]+-)?(?P<issue>\d+)-"),
    re.compile(r"factory/work-checkpoints/issue-(?P<issue>\d+)/"),
    re.compile(r"issue[-/](?P<issue>\d+)"),
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
    proc = run(["git", "-C", str(repo_root), "merge-base", "--is-ancestor", ancestor_ref, descendant_ref], check=False)
    return proc.returncode == 0


def fetch_open_pr_heads(repo: str) -> dict[str, list[dict[str, Any]]]:
    """Fetch open PR heads grouped by branch name."""
    proc = run([
        "gh", "pr", "list", "--repo", repo, "--state", "open", "--limit", "500",
        "--json", "number,headRefName,isDraft,updatedAt,labels,title,url",
    ], check=False)
    if proc.returncode != 0:
        return {}
    try:
        prs = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return {}
    by_head: dict[str, list[dict[str, Any]]] = {}
    for pr in prs:
        head = str(pr.get("headRefName") or "")
        if not head:
            continue
        by_head.setdefault(head, []).append(pr)
    return by_head


def fetch_protected_branches(repo: str) -> set[str]:
    """Fetch protected branch names from GitHub."""
    proc = run(["gh", "api", f"repos/{repo}/branches?protected=true&per_page=100", "--paginate", "--slurp"], check=False)
    if proc.returncode != 0:
        return set()
    try:
        pages = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return set()
    protected: set[str] = set()
    for page in pages:
        if not isinstance(page, list):
            continue
        for item in page:
            name = item.get("name") if isinstance(item, dict) else None
            if isinstance(name, str):
                protected.add(name)
    return protected


def fetch_issue_signal(repo: str, issue_number: int) -> LeaseSignal | None:
    """Fetch lease-relevant issue metadata from GitHub."""
    proc = run(["gh", "api", f"repos/{repo}/issues/{issue_number}"], check=False)
    if proc.returncode != 0:
        return None
    try:
        issue = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(issue, dict):
        return None
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


def active_lease(signal: LeaseSignal | None, now: datetime) -> tuple[bool, str | None]:
    """Return whether a linked target has an active, unexpired factory lease."""
    if signal is None:
        return False, None
    owner = signal.owner
    if owner is None:
        # Multiple owners or no owner: multiple means ambiguous/unsafe.
        owners = sorted(label for label in signal.labels if OWNER_RE.fullmatch(label) and label != "factory:unowned")
        if len(owners) > 1:
            return True, f"ambiguous active owners on {signal.target}"
        return False, None
    if signal.state.lower() == "closed":
        return False, None
    updated = signal.updated_at
    if owner == "factory:local":
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


def unexpired_handoff(branch: BranchInfo, linked_signal: LeaseSignal | None, now: datetime) -> tuple[bool, str | None]:
    """Return whether a branch represents an unexpired handoff/checkpoint."""
    if not branch.name.startswith(CHECKPOINT_PREFIX):
        return False, None
    # Checkpoint branches are persisted handoff/recovery refs. Treat as unexpired
    # unless clearly old and not tied to active/open work.
    if linked_signal and linked_signal.state.lower() == "open":
        return True, f"open linked target for checkpoint handoff {linked_signal.target}"
    if now - branch.committed_at <= timedelta(days=DEFAULT_AGE_DAYS):
        return True, "recent checkpoint handoff branch"
    # If linked issue/PR is closed and branch is old, allow normal age/merge
    # evaluation to decide; still conservative because other guards apply.
    return False, None


def evaluate_branch(
    branch: BranchInfo,
    *,
    default_branch: str,
    protected_names: set[str],
    open_pr_heads: Mapping[str, Sequence[Mapping[str, Any]]],
    live_worktree_refs: set[str],
    now: datetime,
    age_days: int,
    is_merged: Callable[[BranchInfo], bool],
    lease_lookup: Callable[[int], LeaseSignal | None],
) -> Decision:
    """Evaluate one branch and return a pruning decision."""
    age = (now - branch.committed_at).total_seconds() / 86400.0
    issue = linked_issue_number(branch.name)
    open_prs = list(open_pr_heads.get(branch.name, ()))
    open_pr = len(open_prs) > 0
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

    signal = lease_lookup(issue) if issue is not None else None
    leased, lease_reason = active_lease(signal, now)
    if leased and lease_reason:
        reasons.append(lease_reason)
    handoff_blocked, handoff_reason = unexpired_handoff(branch, signal, now)
    if handoff_blocked and handoff_reason:
        reasons.append(handoff_reason)

    merged = False
    if is_stale_scope_branch(branch.name):
        try:
            merged = is_merged(branch)
        except Exception as exc:
            reasons.append(f"unable to verify merged state: {exc}")

    if age < age_days:
        reasons.append(f"younger than {age_days} days")

    if not merged and age >= age_days:
        # "merged or abandoned for more than 14 days"
        reasons.append("age threshold met and branch is not merged; treated as abandoned candidate only with other safety checks")

    # Eligible only when it matches scope, has no hard protections, and is
    # merged-or-abandoned and older than threshold.
    hard_protections = any(
        r in reasons
        for r in (
            "protected branch",
            "default or release ref",
            "open PR exists",
            "checked out in live local worktree",
            "outside factory/local/backup scope",
        )
    ) or leased or handoff_blocked or any(r.startswith("unable to verify") for r in reasons)

    stale_enough = age >= age_days
    eligible = (not hard_protections) and stale_enough and (merged or True)
    # "merged or abandoned for more than 14 days": abandoned means no open PR,
    # not protected, old enough, and not actively leased/handoff-blocked.
    if eligible:
        return Decision(
            branch=branch.name,
            action="delete",
            reasons=(f"eligible: {'merged' if merged else 'abandoned'} for {age:.1f} days",),
            category=category,
            age_days=round(age, 2),
            merged=merged,
            open_pr=open_pr,
            linked_issue=issue,
        )

    # Normalize skip reasons: keep the most relevant ones.
    filtered = [r for r in reasons if not r.startswith("age threshold met and branch is not merged")]
    if not filtered:
        filtered = ["not eligible"]
    if stale_enough and (merged or not open_pr) and hard_protections:
        pass
    elif not stale_enough and "younger than" not in " ".join(filtered):
        filtered.append(f"younger than {age_days} days")
    return Decision(
        branch=branch.name,
        action="skip",
        reasons=tuple(dict.fromkeys(filtered)),
        category=category,
        age_days=round(age, 2),
        merged=merged,
        open_pr=open_pr,
        linked_issue=issue,
    )


def delete_remote_branch(repo_root: Path, remote: str, branch: str) -> None:
    """Delete a remote branch."""
    run(["git", "-C", str(repo_root), "push", remote, "--delete", branch])


def render_report(decisions: list[Decision], *, mode: str, now: datetime, remote: str, age_days: int) -> str:
    """Render a human-readable prune report."""
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
            lines.append(
                f"- `{d.branch}` — {'merged' if d.merged else 'abandoned'}, age={d.age_days}d, issue={d.linked_issue or 'n/a'}; { '; '.join(d.reasons)}"
            )
    else:
        lines.append("- (none)")
    lines.extend(["", "## Skipped branches"])
    for d in sorted(skip, key=lambda x: x.branch):
        lines.append(
            f"- `{d.branch}` — {'merged' if d.merged else 'not merged'}, age={d.age_days}d, open_pr={str(d.open_pr).lower()}, issue={d.linked_issue or 'n/a'}; { '; '.join(d.reasons)}"
        )
    lines.append("")
    return "\n".join(lines)


def decide_branches(
    branches: Iterable[BranchInfo],
    *,
    default_branch: str,
    protected_names: set[str],
    open_pr_heads: Mapping[str, Sequence[Mapping[str, Any]]],
    live_worktree_refs: set[str],
    now: datetime,
    age_days: int = DEFAULT_AGE_DAYS,
    is_merged: Callable[[BranchInfo], bool],
    lease_lookup: Callable[[int], LeaseSignal | None],
) -> list[Decision]:
    """Evaluate all branches and return pruning decisions."""
    return [
        evaluate_branch(
            branch,
            default_branch=default_branch,
            protected_names=protected_names,
            open_pr_heads=open_pr_heads,
            live_worktree_refs=live_worktree_refs,
            now=now,
            age_days=age_days,
            is_merged=is_merged,
            lease_lookup=lease_lookup,
        )
        for branch in branches
    ]


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
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
    """Run the stale branch pruning command."""
    args = build_parser().parse_args(argv)
    repo_root = Path.cwd()
    now = utc_now()
    remote = args.remote
    default_branch = remote_default_branch(repo_root, remote)
    branches = list_remote_branches(repo_root, remote)
    if not args.all_branches:
        branches = [b for b in branches if is_stale_scope_branch(b.name)]
    protected = fetch_protected_branches(args.repo) if args.repo else set()
    protected.update({default_branch, "main", "master", "gh-pages"})
    open_pr_heads = fetch_open_pr_heads(args.repo) if args.repo else {}
    live_refs = local_worktree_branches(repo_root)

    lease_cache: dict[int, LeaseSignal | None] = {}

    def lease_lookup(issue_number: int) -> LeaseSignal | None:
        if issue_number in lease_cache:
            return lease_cache[issue_number]
        if not args.repo:
            lease_cache[issue_number] = None
            return None
        lease_cache[issue_number] = fetch_issue_signal(args.repo, issue_number)
        return lease_cache[issue_number]

    def is_merged(branch: BranchInfo) -> bool:
        return is_ancestor(repo_root, f"{remote}/{branch.name}", f"{remote}/{default_branch}")

    decisions = decide_branches(
        branches,
        default_branch=default_branch,
        protected_names=protected,
        open_pr_heads=open_pr_heads,
        live_worktree_refs=live_refs,
        now=now,
        age_days=args.age_days,
        is_merged=is_merged,
        lease_lookup=lease_lookup,
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
                delete_remote_branch(repo_root, remote, decision.branch)
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

"""Deterministic fixture tests for stale factory/local/backup branch pruning."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "prune_stale_factory_branches.py"
SPEC = importlib.util.spec_from_file_location("prune_stale_factory_branches", SCRIPT_PATH)
assert SPEC and SPEC.loader
prune = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = prune
SPEC.loader.exec_module(prune)

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
OLD = NOW - timedelta(days=20)
RECENT = NOW - timedelta(days=2)
VERY_RECENT = NOW - timedelta(minutes=10)


def branch(
    name: str,
    *,
    age: datetime = OLD,
    sha: str = "deadbeef",
    protected: bool = False,
) -> prune.BranchInfo:
    """Build a BranchInfo fixture.

    Args:
        name: Branch name.
        age: Commit timestamp for the branch head.
        sha: Commit SHA for the branch head.
        protected: Whether the branch is marked protected.

    Returns:
        A ``BranchInfo`` fixture for tests.
    """
    return prune.BranchInfo(name=name, sha=sha, committed_at=age, protected=protected)


def decide(
    branches: list[prune.BranchInfo],
    *,
    open_pr_heads: dict[str, list[dict[str, object]]] | None = None,
    live_worktrees: set[str] | None = None,
    protected: set[str] | None = None,
    merged_names: set[str] | None = None,
    lease_signals: dict[int, prune.LeaseSignal | None] | None = None,
    retired_issues: set[int] | None = None,
    default_branch: str = "main",
) -> list[prune.Decision]:
    """Run branch decisions against deterministic fixtures.

    Args:
        branches: Branch fixtures to evaluate.
        open_pr_heads: PR records grouped by head branch name.
        live_worktrees: Branch names checked out in local worktrees.
        protected: Protected branch names.
        merged_names: Branch names treated as merged into the default branch.
        lease_signals: Lease signals keyed by linked issue number.
        retired_issues: Issue numbers marked as retired.
        default_branch: Default branch name for evaluation.

    Returns:
        A list of pruning decisions.
    """
    pr_records = open_pr_heads or {}
    live_worktree_refs = set(live_worktrees or set())
    protected_names = set(protected or set())
    merged = set(merged_names or set())
    leases = lease_signals or {}
    retired = set(retired_issues or set())

    return prune.decide_branches(
        branches,
        default_branch=default_branch,
        protected_names=protected_names,
        pr_records=pr_records,
        live_worktree_refs=live_worktree_refs,
        now=NOW,
        age_days=14,
        is_merged=lambda b: b.name in merged,
        lease_lookup=lambda issue: leases.get(issue),
        retirement_lookup=lambda issue: issue in retired,
    )


def by_name(decisions: list[prune.Decision]) -> dict[str, prune.Decision]:
    """Index decisions by branch name.

    Args:
        decisions: Decisions to index.

    Returns:
        Mapping of branch name to decision.
    """
    return {d.branch: d for d in decisions}


def test_preserves_pr_backed_branch_even_if_old_and_merged():
    """Preserve branches that have an open PR."""
    decisions = decide(
        [branch("factory/12-4749-prune")],
        open_pr_heads={"factory/12-4749-prune": [{"number": 999}]},
        merged_names={"factory/12-4749-prune"},
    )
    d = by_name(decisions)["factory/12-4749-prune"]
    assert not d.eligible
    assert d.open_pr is True
    assert "open PR exists" in d.reasons


def test_preserves_active_local_factory_lease_by_verified_recent_activity():
    """Preserve branches with a verified active local factory lease."""
    signal = prune.LeaseSignal(
        target="issue:4749",
        state="open",
        owner="factory:local",
        labels=frozenset({"factory", "factory:local", "factory:building"}),
        updated_at=VERY_RECENT,
    )
    decisions = decide([branch("local-factory/i4749")], lease_signals={4749: signal})
    d = by_name(decisions)["local-factory/i4749"]
    assert not d.eligible
    assert any("active local lease" in r for r in d.reasons)


def test_preserves_local_lease_within_shared_ttl():
    """Preserve local leases within the shared 24-hour TTL (not expired at 3h)."""
    signal = prune.LeaseSignal(
        target="issue:4749",
        state="open",
        owner="factory:local",
        labels=frozenset({"factory", "factory:local", "factory:building"}),
        updated_at=NOW - timedelta(hours=3),
    )
    decisions = decide(
        [branch("local-factory/i4749")],
        lease_signals={4749: signal},
        merged_names={"local-factory/i4749"},
    )
    d = by_name(decisions)["local-factory/i4749"]
    assert not d.eligible
    assert any("active local lease" in r for r in d.reasons)


def test_expired_local_lease_can_be_pruned_when_otherwise_eligible():
    """Allow pruning when a local lease is expired by verified inactivity."""
    signal = prune.LeaseSignal(
        target="issue:4749",
        state="open",
        owner="factory:local",
        labels=frozenset({"factory", "factory:local", "factory:building"}),
        updated_at=NOW - timedelta(hours=25),
    )
    decisions = decide(
        [branch("local-factory/i4749")],
        lease_signals={4749: signal},
        merged_names={"local-factory/i4749"},
    )
    d = by_name(decisions)["local-factory/i4749"]
    assert d.eligible
    assert d.merged is True


def test_preserves_numbered_lease_when_expiry_cannot_be_verified():
    """Preserve numbered leases when inactivity cannot be verified."""
    # Numbered leases require verified inactivity and no active workflow run;
    # without workflow evidence the script must be conservative.
    signal = prune.LeaseSignal(
        target="issue:5001",
        state="open",
        owner="factory:46",
        labels=frozenset({"factory", "factory:46", "factory:building"}),
        updated_at=NOW - timedelta(hours=2),
    )
    decisions = decide([branch("factory/46-5001-example")], lease_signals={5001: signal})
    d = by_name(decisions)["factory/46-5001-example"]
    assert not d.eligible
    assert any("cannot verify numbered lease expiry" in r for r in d.reasons)


def test_preserves_checkpoint_handoff_branch_without_incorporation_proof():
    """Never auto-delete checkpoint branches; retirement requires incorporation proof."""
    signal = prune.LeaseSignal(
        target="issue:4853",
        state="open",
        owner="factory:unowned",
        labels=frozenset({"factory", "factory:unowned", "factory:changes-requested"}),
        updated_at=NOW - timedelta(days=1),
    )
    decisions = decide(
        [branch("factory/work-checkpoints/issue-4853/kilo-auto-free/43724877464", age=RECENT)],
        lease_signals={4853: signal},
    )
    d = by_name(decisions)["factory/work-checkpoints/issue-4853/kilo-auto-free/43724877464"]
    assert not d.eligible
    assert any(
        "checkpoint branch requires explicit incorporated-retirement proof" in r for r in d.reasons
    )


def test_preserves_main_protected_and_release_refs():
    """Preserve main, protected, and release refs."""
    decisions = decide(
        [
            branch("main"),
            branch("master"),
            branch("release/1.2.3"),
            branch("factory/protected-case", protected=True),
        ],
        protected={"main", "master"},
        merged_names={"release/1.2.3", "factory/protected-case"},
    )
    results = by_name(decisions)
    assert not results["main"].eligible
    assert not results["master"].eligible
    assert not results["release/1.2.3"].eligible
    assert not results["factory/protected-case"].eligible
    reasons = results["release/1.2.3"].reasons
    assert "default or release ref" in reasons or "protected branch" in reasons


def test_preserves_live_local_worktree_branch():
    """Preserve branches checked out in live local worktrees."""
    decisions = decide(
        [branch("local-factory/i4999")],
        live_worktrees={"local-factory/i4999"},
        merged_names={"local-factory/i4999"},
    )
    d = by_name(decisions)["local-factory/i4999"]
    assert not d.eligible
    assert "checked out in live local worktree" in d.reasons


def test_eligible_stale_merged_factory_branch_with_no_open_pr_or_active_lease():
    """Mark stale merged factory branches eligible when unprotected."""
    decisions = decide(
        [branch("factory/12-4000-old-fix")],
        merged_names={"factory/12-4000-old-fix"},
    )
    d = by_name(decisions)["factory/12-4000-old-fix"]
    assert d.eligible
    assert d.merged is True


def test_eligible_stale_abandoned_backup_branch_with_no_open_pr_or_active_lease():
    """Mark stale abandoned backup branches eligible when unprotected."""
    decisions = decide([branch("backup/old-manual-snapshot")])
    d = by_name(decisions)["backup/old-manual-snapshot"]
    assert d.eligible
    assert d.merged is False
    assert any("abandoned" in r for r in d.reasons)


def test_skips_recent_branches_even_if_merged_and_scoped():
    """Skip branches younger than the age threshold."""
    decisions = decide(
        [branch("local-factory/recent", age=RECENT)],
        merged_names={"local-factory/recent"},
    )
    d = by_name(decisions)["local-factory/recent"]
    assert not d.eligible
    assert any("younger than 14 days" in r for r in d.reasons)


def test_closed_issue_checkpoint_branch_still_requires_retirement_proof():
    """Closed linked work does not make checkpoint branches auto-deletable."""
    signal = prune.LeaseSignal(
        target="issue:4853",
        state="closed",
        owner=None,
        labels=frozenset({"factory", "factory:unowned"}),
        updated_at=NOW - timedelta(days=30),
    )
    decisions = decide(
        [branch("factory/work-checkpoints/issue-4853/kilo-auto-free/43724877464")],
        lease_signals={4853: signal},
    )
    d = by_name(decisions)["factory/work-checkpoints/issue-4853/kilo-auto-free/43724877464"]
    assert not d.eligible
    assert any(
        "checkpoint branch requires explicit incorporated-retirement proof" in r for r in d.reasons
    )


def test_local_numeric_branch_resolves_issue_for_lease_check():
    """Recognize local/<issue>-... branches so active leases protect them."""
    signal = prune.LeaseSignal(
        target="issue:4504",
        state="open",
        owner="factory:local",
        labels=frozenset({"factory", "factory:local", "factory:building"}),
        updated_at=VERY_RECENT,
    )
    decisions = decide([branch("local/4504-network-budget")], lease_signals={4504: signal})
    d = by_name(decisions)["local/4504-network-budget"]
    assert d.linked_issue == 4504
    assert not d.eligible
    assert any("active local lease" in r for r in d.reasons)


def test_local_acp_branch_resolves_issue_for_lease_check():
    """Recognize local/acp-<issue> branches so active leases protect them."""
    signal = prune.LeaseSignal(
        target="issue:3802",
        state="open",
        owner="factory:local",
        labels=frozenset({"factory", "factory:local", "factory:building"}),
        updated_at=VERY_RECENT,
    )
    decisions = decide([branch("local/acp-3802")], lease_signals={3802: signal})
    d = by_name(decisions)["local/acp-3802"]
    assert d.linked_issue == 3802
    assert not d.eligible
    assert any("active local lease" in r for r in d.reasons)


def test_preserves_no_progress_retired_branch_even_if_old_and_merged():
    """Never delete a branch whose issue records no-progress retirement."""
    decisions = decide(
        [branch("factory/12-5001-retired")],
        merged_names={"factory/12-5001-retired"},
        retired_issues={5001},
    )
    d = by_name(decisions)["factory/12-5001-retired"]
    assert not d.eligible
    assert any("preserved by no-progress retirement" in r for r in d.reasons)


def test_recently_closed_pr_waits_full_period_even_with_old_commit():
    """A PR closed today does not make a month-old commit immediately deletable."""
    old_commit = NOW - timedelta(days=30)
    decisions = decide(
        [branch("factory/46-5100-abandoned", age=old_commit)],
        open_pr_heads={
            "factory/46-5100-abandoned": [
                {"number": 700, "state": "CLOSED", "closedAt": (NOW - timedelta(days=2)).isoformat()},
            ]
        },
    )
    d = by_name(decisions)["factory/46-5100-abandoned"]
    assert not d.eligible
    assert any("waiting period since merge/abandonment not met" in r for r in d.reasons)


def test_recently_merged_pr_waits_full_period_even_with_old_commit():
    """The wait starts at merge time, not at the last commit on the branch."""
    old_commit = NOW - timedelta(days=45)
    decisions = decide(
        [branch("factory/46-5101-merged", age=old_commit)],
        open_pr_heads={
            "factory/46-5101-merged": [
                {"number": 701, "state": "MERGED", "mergedAt": (NOW - timedelta(days=3)).isoformat()},
            ]
        },
        merged_names={"factory/46-5101-merged"},
    )
    d = by_name(decisions)["factory/46-5101-merged"]
    assert not d.eligible
    assert any("waiting period since merge/abandonment not met" in r for r in d.reasons)


def test_settled_pr_without_date_fails_closed():
    """A settled PR with no parseable date cannot establish the wait; keep the branch."""
    decisions = decide(
        [branch("factory/46-5102-nodate")],
        open_pr_heads={
            "factory/46-5102-nodate": [{"number": 702, "state": "CLOSED"}]
        },
    )
    d = by_name(decisions)["factory/46-5102-nodate"]
    assert not d.eligible
    assert any("waiting period since merge/abandonment cannot be established" in r for r in d.reasons)


def test_old_closed_pr_after_full_wait_is_eligible():
    """A branch abandoned for more than 14 days after PR close stays eligible."""
    old_commit = NOW - timedelta(days=40)
    decisions = decide(
        [branch("factory/46-5103-oldabandoned", age=old_commit)],
        open_pr_heads={
            "factory/46-5103-oldabandoned": [
                {"number": 703, "state": "CLOSED", "closedAt": (NOW - timedelta(days=30)).isoformat()},
            ]
        },
    )
    d = by_name(decisions)["factory/46-5103-oldabandoned"]
    assert d.eligible
    assert d.merged is False


def test_open_pr_still_protects_branch_with_old_closed_pr():
    """An open PR protects a branch even when an older settled PR exists."""
    decisions = decide(
        [branch("factory/46-5104-reopened")],
        open_pr_heads={
            "factory/46-5104-reopened": [
                {"number": 704, "state": "OPEN"},
                {"number": 703, "state": "CLOSED", "closedAt": (NOW - timedelta(days=30)).isoformat()},
            ]
        },
    )
    d = by_name(decisions)["factory/46-5104-reopened"]
    assert not d.eligible
    assert d.open_pr is True
    assert "open PR exists" in d.reasons


class _FakeResult:
    """Minimal CompletedProcess stand-in for captured command tests."""

    def __init__(self, payload):
        self.returncode = 0
        self.stdout = json.dumps(payload)
        self.stderr = ""


def test_fetch_pr_records_paginates_all_states_without_a_result_cap(monkeypatch):
    """The PR inventory must not silently drop older open PRs at a result limit."""
    calls = []

    def fake_run(cmd, *, check=True):
        calls.append(cmd)
        return _FakeResult([[
            {
                "number": 9,
                "state": "open",
                "head": {"ref": "factory/9-1-open"},
                "merged_at": None,
                "closed_at": None,
            }
        ]])

    monkeypatch.setattr(prune, "run", fake_run)
    records = prune.fetch_pr_records("owner/repo")
    cmd = calls[0]
    assert "--paginate" in cmd and "--slurp" in cmd
    assert "--limit" not in cmd
    assert any("state=all" in arg for arg in cmd)
    assert "factory/9-1-open" in records
    assert records["factory/9-1-open"][0]["state"] == "OPEN"


def test_fetch_issue_retired_uses_supported_pagination_query(monkeypatch):
    """GitHub CLI pagination size belongs in the endpoint query, not a flag."""
    calls = []

    def fake_run(cmd, *, check=True):
        calls.append(cmd)
        return _FakeResult([[
            {"body": "retired <!-- comic-pile-factory-no-progress-retired-v1:issue-1:pr-2:sha-x:epoch-3 -->"}
        ]])

    monkeypatch.setattr(prune, "run", fake_run)
    assert prune.fetch_issue_retired("owner/repo", 1) is True
    cmd = calls[0]
    assert "--per_page" not in cmd
    assert "--paginate" in cmd and "--slurp" in cmd
    assert any(arg.endswith("comments?per_page=100") for arg in cmd)


def test_normalize_repo_slug_accepts_common_remote_forms() -> None:
    """Normalize owner/name, SSH, and HTTPS remote forms for comparison."""
    assert prune.normalize_repo_slug("JoshCLWren/comic-pile") == "joshclwren/comic-pile"
    assert (
        prune.normalize_repo_slug("https://github.com/JoshCLWren/comic-pile.git")
        == "joshclwren/comic-pile"
    )
    assert (
        prune.normalize_repo_slug("git@github.com:JoshCLWren/comic-pile.git")
        == "joshclwren/comic-pile"
    )


def test_remote_github_repo_resolves_remote_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve the GitHub repository slug for a configured git remote."""

    def fake_run(cmd: list[str], *, check: bool = True) -> prune.subprocess.CompletedProcess[str]:
        """Return a fake git remote URL lookup result.

        Args:
            cmd: Command arguments passed to the runner.
            check: Whether failures should raise.

        Returns:
            Completed process containing the configured remote URL.
        """
        assert cmd[:4] == ["git", "-C", "/repo", "remote"]
        return prune.subprocess.CompletedProcess(
            cmd,
            0,
            stdout="git@github.com:JoshCLWren/comic-pile.git\n",
            stderr="",
        )

    monkeypatch.setattr(prune, "run", fake_run)
    assert prune.remote_github_repo(Path("/repo"), "origin") == "joshclwren/comic-pile"


def test_remote_github_repo_returns_none_when_unresolved(monkeypatch: pytest.MonkeyPatch) -> None:
    """Return None when the remote URL cannot be resolved to a GitHub slug."""

    def fake_run(cmd: list[str], *, check: bool = True) -> prune.subprocess.CompletedProcess[str]:
        """Return a failed git remote lookup.

        Args:
            cmd: Command arguments passed to the runner.
            check: Whether failures should raise.

        Returns:
            Completed process representing a missing remote.
        """
        return prune.subprocess.CompletedProcess(cmd, 1, stdout="", stderr="missing")

    monkeypatch.setattr(prune, "run", fake_run)
    assert prune.remote_github_repo(Path("/repo"), "origin") is None

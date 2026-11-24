"""Focused, offline tests for deployment-gated release-ledger recovery."""

from __future__ import annotations

import argparse
import importlib.util
import sys
import urllib.parse
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "release_recovery.py"
SPEC = importlib.util.spec_from_file_location("release_recovery", SCRIPT_PATH)
assert SPEC and SPEC.loader
recovery = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = recovery
SPEC.loader.exec_module(recovery)


def source(number: int, *, merged_at: str | None = None) -> recovery.Source:
    """Build an exact merged-PR source with a valid synthetic commit SHA."""
    return recovery.Source(
        number=number,
        merged_at=merged_at or datetime.now(UTC).isoformat(),
        merge_commit_sha=f"{number:040x}",
        title=f"Reader-visible change {number}",
    )


def pull_item(number: int, timestamp: datetime, **overrides: object) -> dict[str, object]:
    """Build one bounded GitHub pull-list response item."""
    item: dict[str, object] = {
        "number": number,
        "title": f"Change {number}",
        "merged_at": timestamp.isoformat(),
        "updated_at": timestamp.isoformat(),
        "merge_commit_sha": f"{number:040x}",
        "base": {"ref": "main"},
    }
    item.update(overrides)
    return item


def test_production_revision_requires_healthy_native_identity() -> None:
    """Only a healthy native production response can authorize publication."""
    live_sha = "a" * 40
    valid = {
        "status": "ok",
        "build": {"package": "comicpile-vercel-native", "revision": live_sha},
    }
    assert recovery.production_revision(valid) == live_sha

    invalid_payloads = [
        None,
        {"status": "degraded", "build": valid["build"]},
        {"status": "ok", "build": {"package": "other", "revision": live_sha}},
        {"status": "ok", "build": {"package": "comicpile-vercel-native"}},
        {
            "status": "ok",
            "build": {"package": "comicpile-vercel-native", "revision": "not-a-sha"},
        },
    ]
    for payload in invalid_payloads:
        with pytest.raises(recovery.RecoveryError):
            recovery.production_revision(payload)


def test_deployed_sources_require_each_merge_commit_in_live_revision() -> None:
    """Merged history alone is insufficient; every selected SHA must be live."""
    first = source(1)
    undeployed = source(2)
    third = source(3)
    live_sha = "f" * 40
    deployed_shas = {first.merge_commit_sha, third.merge_commit_sha}
    calls: list[tuple[str, str]] = []

    def is_ancestor(ancestor: str, descendant: str) -> bool:
        calls.append((ancestor, descendant))
        return ancestor in deployed_shas

    selected = recovery.deployed_sources(
        [first, undeployed, third], live_sha, is_ancestor=is_ancestor
    )

    assert selected == [first, third]
    assert calls == [
        (first.merge_commit_sha, live_sha),
        (undeployed.merge_commit_sha, live_sha),
        (third.merge_commit_sha, live_sha),
    ]


def test_select_missing_source_is_oldest_first_and_exact_retry_is_noop() -> None:
    """An exact ledger row is preserved, and the oldest absent source is chosen."""
    first = source(1)
    second = source(2)
    third = source(3)

    selected = recovery.select_missing_source(
        [first, second, third],
        [(first.number, first.merge_commit_sha)],
    )
    assert selected == second

    assert (
        recovery.select_missing_source(
            [first, second],
            [
                (first.number, first.merge_commit_sha),
                (second.number, second.merge_commit_sha),
            ],
        )
        is None
    )


def test_select_missing_source_fails_on_partial_or_ambiguous_provenance() -> None:
    """Partial legacy identities and cross-bound rows never get overwritten."""
    candidate = source(7)
    conflicting_rows = [
        [(candidate.number, None)],
        [(None, candidate.merge_commit_sha)],
        [(candidate.number, "a" * 40)],
        [(8, candidate.merge_commit_sha)],
        [
            (candidate.number, candidate.merge_commit_sha),
            (candidate.number, candidate.merge_commit_sha),
        ],
    ]
    for rows in conflicting_rows:
        with pytest.raises(recovery.RecoveryError, match="provenance conflict"):
            recovery.select_missing_source([candidate], rows)


def test_discovery_filters_to_recent_merged_main_pulls() -> None:
    """Discovery ignores unmerged, non-main and out-of-window pull records."""
    recent = datetime.now(UTC) - timedelta(hours=1)
    old = recent - timedelta(days=5)
    items = [
        pull_item(4, recent),
        pull_item(3, recent, merged_at=None),
        pull_item(2, recent, base={"ref": "develop"}),
        pull_item(1, old),
    ]
    with patch.object(recovery, "_github_request", return_value=items) as request:
        selected = recovery._discover("owner/repo", since_hours=24)

    assert [item.number for item in selected] == [4]
    path = request.call_args.args[0]
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
    assert query["state"] == ["closed"]
    assert query["base"] == ["main"]
    assert query["sort"] == ["updated"]
    assert query["direction"] == ["desc"]
    assert query["page"] == ["1"]


def test_discovery_stops_at_the_updated_at_cutoff() -> None:
    """A full page older than the lookback terminates without another request."""
    old = datetime.now(UTC) - timedelta(days=5)
    items = [pull_item(number, old) for number in range(1, 101)]
    with patch.object(recovery, "_github_request", return_value=items) as request:
        assert recovery._discover("owner/repo", since_hours=24) == []
    assert request.call_count == 1


def test_discovery_fails_closed_at_its_page_bound() -> None:
    """Three still-current full pages fail rather than becoming an unbounded scan."""
    recent = datetime.now(UTC)
    pages = [
        [pull_item(page * 100 + number, recent) for number in range(1, 101)]
        for page in range(3)
    ]
    with patch.object(recovery, "_github_request", side_effect=pages) as request:
        with pytest.raises(recovery.RecoveryError, match="bounded lookback"):
            recovery._discover("owner/repo", since_hours=72)
    assert request.call_count == 3


@pytest.mark.parametrize("hours", [0, 169])
def test_discovery_rejects_unbounded_lookbacks(hours: int) -> None:
    """The recovery window cannot be disabled or expanded beyond seven days."""
    with pytest.raises(recovery.RecoveryError, match="between 1 and 168"):
        recovery._discover("owner/repo", since_hours=hours)


def test_merged_but_not_yet_deployed_explicit_pr_waits_without_ledger_write() -> None:
    """An early merge event exits cleanly without selecting or checking a write."""
    args = argparse.Namespace(repository="owner/repo", pr=1, since_hours=72)
    candidate = source(1)
    with (
        patch.object(recovery, "_verified_live_revision", return_value="f" * 40),
        patch.object(recovery, "_fetch_one", return_value=candidate),
        patch.object(recovery, "_git_ancestor", return_value=False),
        patch.object(recovery, "_existing_source_rows") as ledger,
        patch.object(recovery, "_write_outputs") as outputs,
    ):
        assert recovery._select(args) == 0

    ledger.assert_not_called()
    payload = outputs.call_args.args[0]
    assert payload["needed"] is False
    assert payload["reason"] == "awaiting_deployment"


def test_verify_deployed_refuses_a_merge_missing_from_live_production() -> None:
    """The pre-publication check blocks a rollback or failed deployment."""
    args = argparse.Namespace(merge_sha="1" * 40)
    with (
        patch.object(recovery, "_verified_live_revision", return_value="f" * 40),
        patch.object(recovery, "_git_ancestor", return_value=False),
        patch.object(recovery, "_write_outputs") as outputs,
    ):
        with pytest.raises(recovery.RecoveryError, match="refusing publication"):
            recovery._verify_deployed(args)
    outputs.assert_not_called()


def test_verify_deployed_accepts_only_an_actual_live_ancestor() -> None:
    """A selected merge is emitted only after its live ancestry is confirmed."""
    args = argparse.Namespace(merge_sha="1" * 40)
    with (
        patch.object(recovery, "_verified_live_revision", return_value="f" * 40),
        patch.object(recovery, "_git_ancestor", return_value=True) as ancestor,
        patch.object(recovery, "_write_outputs") as outputs,
    ):
        assert recovery._verify_deployed(args) == 0
    ancestor.assert_called_once_with("1" * 40, "f" * 40)
    assert outputs.call_args.args[0]["deployed"] is True


def test_ledger_lookup_requires_an_explicit_trusted_dsn() -> None:
    """Discovery never silently falls back to an ambient database connection."""
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(recovery.RecoveryError, match="RELEASE_NEON_DATABASE_URL"):
            recovery._existing_source_rows("owner/repo", [source(1)])


def test_workflow_recovers_only_after_deploy_success_and_rechecks_before_publish() -> None:
    """The trusted workflow preserves deployment, job and credential boundaries."""
    workflow_path = ROOT / ".github" / "workflows" / "release-writer.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    triggers = workflow[True] if True in workflow else workflow["on"]
    assert triggers["workflow_run"] == {
        "workflows": ["Deploy Production"],
        "types": ["completed"],
        "branches": ["main"],
    }

    discover = workflow["jobs"]["discover"]
    assert "workflow_run.conclusion == 'success'" in discover["if"]
    generate = workflow["jobs"]["generate"]
    assert generate["needs"] == "discover"
    assert "RELEASE_NEON_DATABASE_URL" not in yaml.dump(generate)
    assert "NEON_API_KEY" not in yaml.dump(generate)

    persist = workflow["jobs"]["persist"]
    assert persist["needs"] == ["discover", "generate"]
    assert persist["steps"][0]["with"]["fetch-depth"] == 0
    steps = {step["name"]: step for step in persist["steps"] if "name" in step}
    verify = steps["Verify selected merge is live before publication"]
    grounding = steps["Classify test-only public candidates as internal"]
    publish = steps["Validate and publish directly to Neon"]
    assert "verify-deployed" in verify["run"]
    assert "NEON_API_KEY" not in verify.get("env", {})
    assert "verify-public" in grounding["run"]
    assert "NEON_API_KEY" not in grounding.get("env", {})
    assert list(steps).index(verify["name"]) < list(steps).index(grounding["name"])
    assert list(steps).index(grounding["name"]) < list(steps).index(publish["name"])


def test_release_writer_documents_the_bounded_automatic_delay() -> None:
    """The operating contract states the automatic retry and execution bounds."""
    document = (ROOT / "docs" / "RELEASE_WRITER.md").read_text(encoding="utf-8")
    assert "72-hour lookback" in document
    assert "at most 70 minutes of job execution" in document
    assert "one per run, oldest first" in document
    assert "does not change any automation schedule" in document
    assert "manual refresh" in document
    assert "durable internal outcome" in document

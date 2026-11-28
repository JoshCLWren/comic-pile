"""Focused tests for bounded, deployment-gated release recovery (issue #5693).

These tests use only injected fakes: they never call GitHub, production health,
or a database. They cover the failure classes that strand a release note and
the idempotency/deployment invariants required by the issue contract.
"""

from __future__ import annotations

import json
import socket
import urllib.error
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from scripts import release_recovery as recovery

DEPLOYED_SHA = "a" * 40
OLDER_SHA = "b" * 40
UNDEPLOYED_SHA = "c" * 40


def _health(revision: str = DEPLOYED_SHA, status: str = "ok") -> dict[str, object]:
    return {
        "status": status,
        "build": {
            "package": recovery.NATIVE_BUILD_PACKAGE,
            "revision": revision,
        },
    }


def _pull(number: int, sha: str, hours_ago: float = 1) -> dict[str, object]:
    merged_at = (
        (datetime.now(UTC) - timedelta(hours=hours_ago))
        .isoformat()
        .replace("+00:00", "Z")
    )
    return {
        "number": number,
        "merged_at": merged_at,
        "updated_at": merged_at,
        "merge_commit_sha": sha,
        "title": f"Reader change {number}",
        "base": {"ref": "main"},
    }


def _pull_pages(pulls: list[dict[str, object]]) -> recovery.FetchJson:
    def fetch(url: str) -> object:
        parsed = urlparse(url)
        assert parsed.path.endswith("/pulls")
        page = int(parse_qs(parsed.query).get("page", ["1"])[0])
        return pulls if page == 1 else []

    return fetch


def test_production_revision_accepts_only_healthy_native_identity() -> None:
    """Only a healthy native production build identity yields a revision."""
    assert recovery.production_revision(_health()) == DEPLOYED_SHA

    for payload in (
        _health(status="degraded"),
        {"status": "ok", "build": {"package": "legacy-python", "revision": DEPLOYED_SHA}},
        {"status": "ok", "build": {"package": recovery.NATIVE_BUILD_PACKAGE}},
        {"status": "ok"},
        [],
    ):
        with pytest.raises(recovery.RecoveryError):
            recovery.production_revision(payload)


def test_deployed_sources_excludes_merges_missing_from_live_revision() -> None:
    """Merges absent from the deployed revision are filtered out."""
    sources = [
        recovery.Source(1, "2026-11-25T00:00:00Z", OLDER_SHA, "older"),
        recovery.Source(2, "2026-11-25T01:00:00Z", UNDEPLOYED_SHA, "not deployed"),
    ]
    deployed = recovery.deployed_sources(
        sources, DEPLOYED_SHA, lambda sha, live: sha == OLDER_SHA
    )
    assert deployed == [sources[0]]


def test_select_missing_source_picks_oldest_unrecorded_source() -> None:
    """The oldest source without a ledger row is selected."""
    sources = [
        recovery.Source(1, "2026-11-25T00:00:00Z", OLDER_SHA, "older"),
        recovery.Source(2, "2026-11-25T01:00:00Z", DEPLOYED_SHA, "newer"),
    ]
    assert recovery.select_missing_source(sources, [(1, OLDER_SHA)]) == sources[1]


def test_select_missing_source_is_idempotent_when_all_recorded() -> None:
    """Repeated selection is a no-op once every source is recorded."""
    sources = [recovery.Source(1, "2026-11-25T00:00:00Z", OLDER_SHA, "older")]
    assert recovery.select_missing_source(sources, [(1, OLDER_SHA)]) is None


def test_select_missing_source_fails_closed_on_ambiguous_provenance() -> None:
    """Ambiguous ledger provenance fails closed instead of guessing."""
    source = recovery.Source(7, "2026-11-25T00:00:00Z", DEPLOYED_SHA, "ambiguous")
    with pytest.raises(recovery.RecoveryError, match="provenance conflict"):
        recovery.select_missing_source([source], [(7, OLDER_SHA), (8, DEPLOYED_SHA)])


def test_select_sources_uses_deployed_provenance_not_just_merge_time() -> None:
    """Only deployed merges are considered even when older undeployed merges exist."""
    pulls = [
        _pull(1, UNDEPLOYED_SHA, hours_ago=3),
        _pull(2, DEPLOYED_SHA, hours_ago=2),
    ]
    seen: dict[str, object] = {}

    def lookup(
        repository: str, numbers: list[int], shas: list[str]
    ) -> list[tuple[int | None, str | None]]:
        seen["numbers"] = numbers
        seen["shas"] = shas
        return []

    summary = recovery.select_sources(
        "JoshCLWren/comic-pile",
        request_json=_pull_pages(pulls),
        fetch_revision=lambda: DEPLOYED_SHA,
        is_ancestor=lambda sha, live: sha == DEPLOYED_SHA,
        lookup=lookup,
    )
    assert summary["needed"] is True
    assert summary["pr_number"] == 2
    assert summary["merge_sha"] == DEPLOYED_SHA
    assert summary["deployed_revision"] == DEPLOYED_SHA
    assert summary["missing_count"] == 1
    # The ledger is queried only for deployed sources; an undeployed merge can
    # never become a release candidate.
    assert seen["numbers"] == [2]
    assert seen["shas"] == [DEPLOYED_SHA]


def test_select_sources_reports_no_work_when_deployed_source_already_recorded() -> None:
    """A recorded deployed source produces no dispatch."""
    summary = recovery.select_sources(
        "JoshCLWren/comic-pile",
        request_json=_pull_pages([_pull(4, DEPLOYED_SHA)]),
        fetch_revision=lambda: DEPLOYED_SHA,
        is_ancestor=lambda sha, live: True,
        lookup=lambda repository, numbers, shas: [(4, DEPLOYED_SHA)],
    )
    assert summary["needed"] is False
    assert summary["pr_number"] is None
    assert summary["missing_count"] == 0


def test_select_sources_rejects_a_lookback_beyond_its_bound() -> None:
    """Discovery lookback is bounded."""
    with pytest.raises(recovery.RecoveryError, match="lookback"):
        recovery.select_sources(
            "JoshCLWren/comic-pile",
            since_hours=recovery.MAX_LOOKBACK_HOURS + 1,
        )


def test_select_sources_fails_closed_when_discovery_exceeds_page_bound() -> None:
    """An unbounded discovery page chain fails closed."""
    full_page = [_pull(index + 1, DEPLOYED_SHA) for index in range(100)]

    def fetch(url: str) -> object:
        return full_page

    with pytest.raises(recovery.RecoveryError, match="bounded lookback"):
        recovery.select_sources(
            "JoshCLWren/comic-pile",
            request_json=fetch,
            fetch_revision=lambda: DEPLOYED_SHA,
        )


def test_verify_deployed_rereads_live_revision_before_publication() -> None:
    """Publication is gated on fresh deployed ancestry."""
    calls: list[str] = []

    def fetch(health_url: str) -> str:
        calls.append(health_url)
        return DEPLOYED_SHA

    assert (
        recovery.verify_deployed(
            DEPLOYED_SHA,
            fetch_revision=fetch,
            is_ancestor=lambda sha, live: sha == live,
        )
        == DEPLOYED_SHA
    )
    assert calls == [recovery.PRODUCTION_HEALTH_URL]

    with pytest.raises(recovery.RecoveryError, match="not contained"):
        recovery.verify_deployed(
            UNDEPLOYED_SHA,
            fetch_revision=fetch,
            is_ancestor=lambda sha, live: sha == DEPLOYED_SHA,
        )


def test_verify_deployed_fails_when_production_is_unhealthy() -> None:
    """An unhealthy production health response blocks verification."""

    def fetch(health_url: str) -> str:
        raise recovery.RecoveryError("production health response is not healthy")

    with pytest.raises(recovery.RecoveryError, match="not healthy"):
        recovery.verify_deployed(DEPLOYED_SHA, fetch_revision=fetch)


def _candidate() -> dict[str, object]:
    return {
        "source_repository": "JoshCLWren/comic-pile",
        "source_pr_number": 9,
        "source_merge_sha": DEPLOYED_SHA,
        "visibility": "public",
        "status": "published",
        "category": "Feature",
        "title": "Reader navigation improves",
        "summary": "The reading queue now keeps your place between visits.",
        "provenance_json": {"reader_reachable_path": "/roll"},
    }


def test_ground_candidate_rewrites_only_a_complete_test_only_diff() -> None:
    """Complete test-only diffs become internal outcomes."""
    grounded, rewritten = recovery.ground_candidate(
        _candidate(),
        repository="JoshCLWren/comic-pile",
        pr_number=9,
        changed_files=lambda repository, pr: ([{"filename": "tests/test_roll.py"}], True),
    )
    assert rewritten is True
    assert grounded["visibility"] == "internal"
    assert grounded["category"] == "Internal"
    provenance = grounded["provenance_json"]
    assert isinstance(provenance, dict)
    assert provenance["reader_reachable"] is False
    assert "reader_reachable_path" not in provenance


def test_ground_candidate_leaves_product_or_incomplete_diffs_untouched() -> None:
    """Product and incomplete diffs are never rewritten."""
    for files, complete in (
        ([{"filename": "frontend/src/pages/RollPage.tsx"}], True),
        ([{"filename": "tests/test_roll.py"}], False),
        ([], True),
    ):
        payload = _candidate()
        grounded, rewritten = recovery.ground_candidate(
            payload,
            repository="JoshCLWren/comic-pile",
            pr_number=9,
            changed_files=lambda repository, pr, files=files, complete=complete: (
                files,
                complete,
            ),
        )
        assert rewritten is False
        assert grounded == payload


def test_ground_candidate_rejects_a_source_mismatch() -> None:
    """A candidate for a different source is rejected."""
    with pytest.raises(recovery.RecoveryError, match="does not match"):
        recovery.ground_candidate(
            _candidate(),
            repository="JoshCLWren/comic-pile",
            pr_number=10,
            changed_files=lambda repository, pr: ([], True),
        )


def test_is_test_file_recognizes_conventional_test_paths() -> None:
    """Conventional test paths are recognized without product heuristics."""
    assert recovery.is_test_file("tests/test_roll.py")
    assert recovery.is_test_file("frontend/src/unit/roll.test.tsx")
    assert recovery.is_test_file("native/roll-service/src/roll_test.rs")
    assert not recovery.is_test_file("frontend/src/pages/RollPage.tsx")
    assert not recovery.is_test_file("scripts/release_writer.py")


def test_load_candidate_rejects_oversized_files(tmp_path: Path) -> None:
    """Staged candidates are size bounded."""
    oversized = tmp_path / "candidate.json"
    oversized.write_text("x" * (recovery.MAX_CANDIDATE_BYTES + 1), encoding="utf-8")
    with pytest.raises(recovery.RecoveryError, match="oversized"):
        recovery._load_candidate(oversized)

    valid = tmp_path / "valid.json"
    valid.write_text(json.dumps(_candidate()), encoding="utf-8")
    assert recovery._load_candidate(valid)["source_pr_number"] == 9

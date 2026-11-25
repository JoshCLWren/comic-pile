"""Focused, offline tests for deployment-gated release-ledger recovery."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

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
    """Build one merged source with a deterministic synthetic commit SHA."""
    return recovery.Source(
        number=number,
        merged_at=merged_at or datetime.now(UTC).isoformat(),
        merge_commit_sha=f"{number:040x}",
        title=f"Reader-visible change {number}",
    )


def healthy(revision: str = "a" * 40) -> dict[str, object]:
    """Build a healthy native production identity payload."""
    return {
        "status": "ok",
        "runtime": "rust",
        "build": {
            "package": "comicpile-vercel-native",
            "revision": revision,
            "version": "0.1.0",
        },
    }


def pull_item(number: int, timestamp: datetime, **overrides: object) -> dict[str, object]:
    """Build one bounded GitHub pull-list item."""
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


def public_candidate(pr_number: int = 12) -> dict[str, object]:
    """Build a staged public candidate matching one selected source."""
    return {
        "source_repository": "JoshCLWren/comic-pile",
        "source_pr_number": pr_number,
        "source_merge_sha": f"{pr_number:040x}",
        "category": "bugfix",
        "title": "Queue covers render for every series",
        "summary": "Readers now see cover art on every queue row.",
        "body": None,
        "visibility": "public",
        "status": "published",
        "provenance_json": {
            "classification": "public",
            "reader_reachable": True,
            "reader_reachable_path": "frontend/src/pages/QueuePage",
        },
    }


class TestProductionRevision:
    """The publication gate trusts only a healthy native build identity."""

    def test_accepts_native_revision(self) -> None:
        """A healthy native identity yields the deployed revision."""
        assert recovery.production_revision(healthy("b" * 40)) == "b" * 40

    @pytest.mark.parametrize(
        "payload",
        [
            {"status": "degraded", "build": {"package": "comicpile-vercel-native"}},
            {"status": "ok", "build": {"package": "other-package", "revision": "a" * 40}},
            {"status": "ok"},
            {"status": "ok", "build": {"package": "comicpile-vercel-native"}},
            "not-an-object",
        ],
    )
    def test_rejects_untrusted_identity(self, payload: object) -> None:
        """Unhealthy or non-native health responses are refused."""
        with pytest.raises(recovery.RecoveryError):
            recovery.production_revision(payload)

    def test_rejects_non_sha_revision(self) -> None:
        """A revision that is not a full commit SHA is refused."""
        with pytest.raises(recovery.RecoveryError):
            recovery.production_revision(healthy("HEAD"))


class TestDeployedSources:
    """Only merges contained in the live revision may be announced."""

    def test_keeps_only_ancestors_of_live_revision(self) -> None:
        """A merged-but-undeployed PR is never selected for publication."""
        deployed = source(2)
        pending = source(3)
        kept = recovery.deployed_sources(
            [deployed, pending],
            "c" * 40,
            is_ancestor=lambda ancestor, _descendant: ancestor == deployed.merge_commit_sha,
        )
        assert kept == [deployed]


class TestSourceSelection:
    """Recovery picks the oldest absent source and never duplicates rows."""

    def test_selects_oldest_missing_source(self) -> None:
        """The oldest source without a ledger row is selected."""
        first, second, third = source(1), source(2), source(3)
        selected = recovery.select_missing_source(
            [first, second, third],
            [(1, first.merge_commit_sha)],
        )
        assert selected == second

    def test_returns_none_when_every_source_is_recorded(self) -> None:
        """A fully reconciled window selects nothing, so recovery is idempotent."""
        first, second = source(1), source(2)
        selected = recovery.select_missing_source(
            [first, second],
            [(1, first.merge_commit_sha), (2, second.merge_commit_sha)],
        )
        assert selected is None

    @pytest.mark.parametrize(
        "rows",
        [
            # A number-only row collides with the source but is not the same identity.
            [(7, None)],
            # A SHA-only row for this exact source lacks its PR number.
            [(None, f"{7:040x}")],
            # A number row carrying the wrong merge SHA is contradictory.
            [(7, "9" * 40)],
        ],
    )
    def test_rejects_ambiguous_provenance(
        self, rows: list[tuple[int | None, str | None]]
    ) -> None:
        """Partial or contradictory provenance fails closed."""
        with pytest.raises(recovery.RecoveryError, match="provenance conflict"):
            recovery.select_missing_source([source(7)], rows)

    @pytest.mark.parametrize("since_hours", [0, -1, 169])
    def test_lookback_is_bounded(self, since_hours: int) -> None:
        """Recovery refuses a lookback outside its documented bound."""
        with pytest.raises(recovery.RecoveryError, match="lookback"):
            recovery._discover("JoshCLWren/comic-pile", since_hours=since_hours)


class TestDiscoveryWindow:
    """Discovery stays inside its documented, bounded recent window."""

    def test_keeps_recent_merges_and_skips_older_ones(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only merges inside the lookback window are candidates."""
        now = datetime.now(UTC)
        monkeypatch.setattr(
            recovery,
            "_github_request",
            lambda _path: [
                pull_item(11, now - timedelta(hours=2)),
                pull_item(10, now - timedelta(hours=200)),
            ],
        )
        discovered = recovery._discover("JoshCLWren/comic-pile", since_hours=72)
        assert [item.number for item in discovered] == [11]

    def test_ignores_pull_requests_that_are_not_merged_to_main(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unmerged, non-main and invalid-SHA payloads are not sources."""
        now = datetime.now(UTC)
        monkeypatch.setattr(
            recovery,
            "_github_request",
            lambda _path: [
                pull_item(20, now, base={"ref": "release"}),
                pull_item(21, now, merged_at=None),
                pull_item(22, now, merge_commit_sha="not-a-sha"),
            ],
        )
        assert recovery._discover("JoshCLWren/comic-pile", since_hours=72) == []

    def test_fails_when_the_bounded_window_is_exhausted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A window that never shrinks fails closed instead of rescanning."""
        now = datetime.now(UTC)
        full_page = [pull_item(100 + offset, now) for offset in range(100)]
        monkeypatch.setattr(recovery, "_github_request", lambda _path: full_page)
        with pytest.raises(recovery.RecoveryError, match="bounded lookback"):
            recovery._discover("JoshCLWren/comic-pile", since_hours=72)


class TestCandidateGrounding:
    """A complete test-only merged diff is internal, never reader-facing."""

    def test_rewrites_test_only_public_candidate_as_internal(self) -> None:
        """Developer-only work is recorded internally instead of published."""
        payload = public_candidate()
        grounded, changed = recovery.ground_candidate(
            payload,
            repository="JoshCLWren/comic-pile",
            pr_number=12,
            changed_files=lambda _repo, _pr: (
                [{"filename": "frontend/src/unit/QueueThreadCard.test.tsx"}],
                True,
            ),
        )
        assert changed is True
        assert grounded["visibility"] == "internal"
        assert grounded["category"] == "Internal"
        provenance = grounded["provenance_json"]
        assert isinstance(provenance, dict)
        assert provenance["reader_reachable"] is False
        assert "reader_reachable_path" not in provenance

    def test_keeps_candidate_when_a_product_file_changed(self) -> None:
        """A diff touching product code stays reader-facing."""
        payload = public_candidate()
        grounded, changed = recovery.ground_candidate(
            payload,
            repository="JoshCLWren/comic-pile",
            pr_number=12,
            changed_files=lambda _repo, _pr: (
                [
                    {"filename": "frontend/src/unit/QueueThreadCard.test.tsx"},
                    {"filename": "frontend/src/pages/QueuePage/QueueThreadCard.tsx"},
                ],
                True,
            ),
        )
        assert changed is False
        assert grounded == payload

    def test_keeps_candidate_when_changed_files_are_incomplete(self) -> None:
        """A truncated changed-file response can never prove test-only work."""
        payload = public_candidate()
        _grounded, changed = recovery.ground_candidate(
            payload,
            repository="JoshCLWren/comic-pile",
            pr_number=12,
            changed_files=lambda _repo, _pr: ([{"filename": "tests/test_x.py"}], False),
        )
        assert changed is False

    def test_keeps_candidate_without_changed_files(self) -> None:
        """An empty diff is not treated as proof that no product file changed."""
        payload = public_candidate()
        _grounded, changed = recovery.ground_candidate(
            payload,
            repository="JoshCLWren/comic-pile",
            pr_number=12,
            changed_files=lambda _repo, _pr: ([], True),
        )
        assert changed is False

    def test_rejects_candidate_from_another_source(self) -> None:
        """A candidate that does not match the selected PR fails closed."""
        with pytest.raises(recovery.RecoveryError, match="does not match"):
            recovery.ground_candidate(
                public_candidate(12),
                repository="JoshCLWren/comic-pile",
                pr_number=13,
                changed_files=lambda _repo, _pr: ([{"filename": "tests/t.py"}], True),
            )

    def test_ignores_already_internal_candidates(self) -> None:
        """Already internal candidates are left untouched."""
        payload = public_candidate()
        payload["visibility"] = "internal"
        _grounded, changed = recovery.ground_candidate(
            payload,
            repository="JoshCLWren/comic-pile",
            pr_number=12,
            changed_files=lambda _repo, _pr: ([{"filename": "tests/t.py"}], True),
        )
        assert changed is False


class TestRecoveryWorkflowWiring:
    """The workflow must recover missed events and gate publication."""

    @staticmethod
    def workflow() -> dict[str, object]:
        """Load the committed release-writer workflow."""
        text = (ROOT / ".github" / "workflows" / "release-writer.yml").read_text(
            encoding="utf-8"
        )
        parsed = yaml.safe_load(text)
        assert isinstance(parsed, dict)
        return parsed

    @staticmethod
    def triggers(workflow: dict[str, object]) -> dict[str, object]:
        """Return the workflow trigger map regardless of YAML 1.1 key parsing."""
        triggers = workflow.get("on", workflow.get(True))
        assert isinstance(triggers, dict)
        return triggers

    def test_recovers_after_a_successful_production_deployment(self) -> None:
        """A successful Deploy Production run re-enters the writer."""
        triggers = self.triggers(self.workflow())
        workflow_run = triggers["workflow_run"]
        assert isinstance(workflow_run, dict)
        assert workflow_run["workflows"] == ["Deploy Production"]
        assert workflow_run["types"] == ["completed"]
        assert workflow_run["branches"] == ["main"]

    def test_discovery_runs_before_generation_and_gates_it(self) -> None:
        """Generation only runs when discovery selected a missing source."""
        jobs = self.workflow()["jobs"]
        assert isinstance(jobs, dict)
        assert "discover" in jobs
        generate = jobs["generate"]
        assert isinstance(generate, dict)
        assert generate["needs"] == "discover"
        assert "needs.discover.outputs.needed == 'true'" in str(generate["if"])

    def test_publication_requires_discovery_and_rechecks_deployment(self) -> None:
        """Publication depends on discovery and re-proves the live deployment."""
        jobs = self.workflow()["jobs"]
        assert isinstance(jobs, dict)
        persist = jobs["persist"]
        assert isinstance(persist, dict)
        assert persist["needs"] == ["discover", "generate"]
        steps = persist["steps"]
        assert isinstance(steps, list)
        commands = "\n".join(
            str(step.get("run", "")) for step in steps if isinstance(step, dict)
        )
        assert "release_recovery.py verify-deployed" in commands
        assert "release_recovery.py ground-candidate" in commands

    def test_generation_uses_the_discovered_source_only(self) -> None:
        """Generation never falls back to an unchecked event PR number."""
        jobs = self.workflow()["jobs"]
        assert isinstance(jobs, dict)
        generate = jobs["generate"]
        assert isinstance(generate, dict)
        steps = generate["steps"]
        assert isinstance(steps, list)
        rendered = json.dumps(steps)
        assert "needs.discover.outputs.pr_number" in rendered
        assert "github.event.pull_request.number || inputs.pr_number" not in rendered

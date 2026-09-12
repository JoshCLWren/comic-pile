"""Regression coverage for post-deploy Vercel deployment pruning."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from scripts.prune_vercel_deployments import (
    DELETE_BATCH_SIZE,
    DeleteOutcome,
    Deployment,
    PruneError,
    backoff_seconds,
    deployment_delete_url,
    is_deployment_id,
    is_protected_delete_error,
    iter_batches,
    main,
    parse_deployment,
    production_alias_id,
    prune_exit_code,
    require_deployment_id,
    run_prune,
    select_keepers,
    select_prune_candidates,
    select_rollback_id,
    verify_project,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY_ROOT / "scripts" / "prune_vercel_deployments.py"
WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "deploy-production.yml"
DOCS = REPOSITORY_ROOT / "docs" / "VERCEL_DEPLOYMENT.md"


def _deployment(
    uid: str,
    *,
    created: int,
    state: str = "READY",
    target: str | None = "production",
    url: str | None = None,
) -> Deployment:
    """Build a deployment fixture.

    Args:
        uid: Deployment id.
        created: Timestamp in milliseconds.
        state: Ready/terminal state.
        target: Environment target.
        url: Optional hostname.

    Returns:
        A :class:`Deployment` row.
    """
    return Deployment(uid=uid, url=url, created=created, state=state, target=target)


class FakeVercel:
    """In-memory Vercel client for prune-policy tests."""

    def __init__(
        self,
        project: Mapping[str, object],
        deployments: list[Deployment],
        delete_results: Mapping[str, DeleteOutcome] | None = None,
    ) -> None:
        """Store project, rows, and optional per-id delete outcomes.

        Args:
            project: Project payload.
            deployments: Known deployments.
            delete_results: Forced outcomes keyed by deployment id.
        """
        self.project = project
        self.deployments = deployments
        self.delete_results = dict(delete_results or {})
        self.deleted: list[str] = []

    def fetch_project(self) -> Mapping[str, object]:
        """Return the stored project payload."""
        return self.project

    def fetch_deployments(self) -> list[Deployment]:
        """Return a copy of the stored deployments."""
        return list(self.deployments)

    def delete_deployment(self, uid: str) -> DeleteOutcome:
        """Record a delete and return the configured or successful outcome."""
        if uid in self.delete_results:
            outcome = self.delete_results[uid]
            if outcome.ok:
                self.deleted.append(uid)
            return outcome
        self.deleted.append(uid)
        return DeleteOutcome(uid, True, 200, False, "DELETED")


def test_is_deployment_id_rejects_project_identifiers() -> None:
    """Only ``dpl_`` ids are valid delete targets."""
    assert is_deployment_id("dpl_abc123") is True
    assert is_deployment_id("comic-pile") is False
    assert is_deployment_id("prj_TLT92644pRPZbZSMoXddCfQLZgK8") is False
    with pytest.raises(PruneError, match="non-deployment"):
        require_deployment_id("comic-pile")


def test_deployment_delete_url_is_deployment_scoped() -> None:
    """Deletes must target ``/v13/deployments/{dpl_}`` and never a project."""
    url = deployment_delete_url("dpl_abc123", "team_1na05XWOpOb6wB1CA4m3GPRT")

    assert url.startswith("https://api.vercel.com/v13/deployments/dpl_abc123?")
    assert "teamId=team_1na05XWOpOb6wB1CA4m3GPRT" in url
    assert "/projects/" not in url
    with pytest.raises(PruneError):
        deployment_delete_url("comic-pile", "team_1na05XWOpOb6wB1CA4m3GPRT")


def test_parse_deployment_accepts_uid_and_createdat_aliases() -> None:
    """List payloads may use ``id``/``createdAt`` or ``uid``/``created``."""
    parsed = parse_deployment(
        {
            "id": "dpl_from_id",
            "createdAt": 100,
            "readyState": "READY",
            "target": "production",
            "url": "comic-pile-from-id.vercel.app",
        }
    )

    assert parsed == Deployment(
        uid="dpl_from_id",
        url="comic-pile-from-id.vercel.app",
        created=100,
        state="READY",
        target="production",
    )
    assert parse_deployment({"uid": "not-a-deployment", "created": 1, "state": "READY"}) is None


def test_production_alias_id_reads_target_object_or_string() -> None:
    """Live production can be a nested object or a bare deployment id."""
    assert production_alias_id({"targets": {"production": {"id": "dpl_live"}}}) == "dpl_live"
    assert production_alias_id({"targets": {"production": "dpl_live"}}) == "dpl_live"
    with pytest.raises(PruneError, match="live production"):
        production_alias_id({"targets": {}})


def test_verify_project_rejects_name_or_id_mismatch() -> None:
    """Refuse to prune a project that is not ComicPile production."""
    project = {"id": "prj_expected", "name": "comic-pile"}

    verify_project(project, project_id="prj_expected", project_name="comic-pile")
    with pytest.raises(PruneError, match="project id"):
        verify_project(project, project_id="prj_other", project_name="comic-pile")
    with pytest.raises(PruneError, match="project name"):
        verify_project(project, project_id="prj_expected", project_name="other")


def test_select_keepers_keeps_live_and_previous_ready_production() -> None:
    """Keep-N=2 is the live alias plus the newest previous READY production."""
    live = _deployment("dpl_live", created=300)
    previous = _deployment("dpl_prev", created=200)
    older = _deployment("dpl_old", created=100)
    failed = _deployment("dpl_fail", created=150, state="ERROR")
    preview = _deployment("dpl_preview", created=250, target="preview")
    building = _deployment("dpl_building", created=400, state="BUILDING", target=None)

    deployments = [older, failed, previous, preview, live, building]
    keepers = select_keepers("dpl_live", deployments)

    assert keepers == {"dpl_live", "dpl_prev", "dpl_building"}
    assert select_rollback_id("dpl_live", deployments) == "dpl_prev"
    candidates = select_prune_candidates(deployments, keepers)
    assert [item.uid for item in candidates] == ["dpl_old", "dpl_fail", "dpl_preview"]


def test_select_keepers_keeps_live_alias_even_when_not_ready() -> None:
    """The live alias is never deletable, even if Vercel reports a non-READY state."""
    live = _deployment("dpl_live", created=300, state="ERROR")
    ready = _deployment("dpl_ready", created=200)
    older = _deployment("dpl_old", created=100)

    keepers = select_keepers("dpl_live", [live, ready, older])

    assert "dpl_live" in keepers
    assert keepers == {"dpl_live", "dpl_ready"}


def test_select_keepers_keeps_only_live_when_no_rollback_exists() -> None:
    """A first production deploy has no previous READY rollback candidate."""
    live = _deployment("dpl_live", created=100)
    canceled = _deployment("dpl_canceled", created=50, state="CANCELED")

    keepers = select_keepers("dpl_live", [live, canceled])

    assert keepers == {"dpl_live"}
    assert select_rollback_id("dpl_live", [live, canceled]) is None


def test_iter_batches_honors_cli_200_limit() -> None:
    """Batches stay at or below the Vercel CLI 200-deletion cap."""
    items = [f"dpl_{index}" for index in range(250)]

    batches = iter_batches(items, DELETE_BATCH_SIZE)

    assert len(batches) == 2
    assert len(batches[0]) == 200
    assert len(batches[1]) == 50
    with pytest.raises(PruneError, match="CLI limit"):
        iter_batches(items, 201)


def test_backoff_seconds_prefers_retry_after() -> None:
    """Rate-limit retries honor Retry-After, otherwise exponential backoff."""
    assert backoff_seconds(1) == 2
    assert backoff_seconds(4) == 16
    assert backoff_seconds(8) == 32
    assert backoff_seconds(1, retry_after=12) == 12
    assert backoff_seconds(1, retry_after=90) == 60


def test_protected_delete_errors_are_treated_as_keepers() -> None:
    """Vercel refusals for the live alias must not be retried as ordinary failures."""
    assert is_protected_delete_error(400, "This is the current production deployment") is True
    assert is_protected_delete_error(403, "cannot be removed because it is aliased") is True
    assert is_protected_delete_error(500, "current production") is False
    assert is_protected_delete_error(400, "unrelated validation") is False


def test_run_prune_deletes_non_keepers_and_never_the_live_alias() -> None:
    """A real prune pass deletes only the selected terminal leftovers."""
    project = {
        "id": "prj_expected",
        "name": "comic-pile",
        "targets": {"production": {"id": "dpl_live", "readyState": "READY"}},
    }
    deployments = [
        _deployment("dpl_old", created=100),
        _deployment("dpl_prev", created=200),
        _deployment("dpl_live", created=300),
        _deployment("dpl_error", created=150, state="ERROR"),
        _deployment("dpl_building", created=400, state="QUEUED", target=None),
    ]
    client = FakeVercel(project, deployments)

    result = run_prune(
        client,
        project_id="prj_expected",
        project_name="comic-pile",
        dry_run=False,
        sleeper=lambda _seconds: None,
        log=lambda _message: None,
    )

    assert result.live_id == "dpl_live"
    assert result.rollback_id == "dpl_prev"
    assert set(result.deleted) == {"dpl_old", "dpl_error"}
    assert "dpl_live" not in client.deleted
    assert "dpl_prev" not in client.deleted
    assert "dpl_building" not in client.deleted
    assert result.failed == ()


def test_run_prune_dry_run_deletes_nothing() -> None:
    """``--dry-run`` reports candidates without calling delete."""
    project = {
        "id": "prj_expected",
        "name": "comic-pile",
        "targets": {"production": "dpl_live"},
    }
    deployments = [
        _deployment("dpl_old", created=100),
        _deployment("dpl_live", created=200),
    ]
    client = FakeVercel(project, deployments)

    result = run_prune(
        client,
        project_id="prj_expected",
        project_name="comic-pile",
        dry_run=True,
        log=lambda _message: None,
    )

    assert result.dry_run is True
    assert result.deleted == ()
    assert client.deleted == []


def test_run_prune_records_failed_deletes() -> None:
    """A single delete failure is recorded without deleting keepers."""
    project = {
        "id": "prj_expected",
        "name": "comic-pile",
        "targets": {"production": {"uid": "dpl_live"}},
    }
    deployments = [
        _deployment("dpl_old", created=100, state="ERROR"),
        _deployment("dpl_live", created=200),
    ]
    client = FakeVercel(
        project,
        deployments,
        delete_results={
            "dpl_old": DeleteOutcome("dpl_old", False, 429, False, "rate limited"),
        },
    )

    result = run_prune(
        client,
        project_id="prj_expected",
        project_name="comic-pile",
        dry_run=False,
        log=lambda _message: None,
    )

    assert result.failed == ("dpl_old",)
    assert client.deleted == []


def test_prune_exit_code_fails_soft_when_requested() -> None:
    """Deploy Production must stay green when prune hits rate limits."""
    assert prune_exit_code(fail_soft=False, failed=False) == 0
    assert prune_exit_code(fail_soft=False, failed=True) == 1
    assert prune_exit_code(fail_soft=True, failed=True) == 0


def test_main_fail_soft_returns_zero_when_credentials_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing token is a prune error, not a reason to fail a finished deploy."""
    monkeypatch.delenv("VERCEL_TOKEN", raising=False)
    monkeypatch.delenv("VERCEL_PROJECT_ID", raising=False)
    monkeypatch.delenv("VERCEL_ORG_ID", raising=False)

    assert main(["--fail-soft"]) == 0
    assert main([]) == 1


def test_script_never_invokes_project_level_vercel_remove() -> None:
    """Automated prune must not call ``vercel remove comic-pile``."""
    source = SCRIPT.read_text(encoding="utf-8")

    assert "subprocess" not in source
    assert "os.system" not in source
    assert "vercel remove comic-pile" not in source
    assert "DELETE_BATCH_SIZE = 200" in source
    assert "keep-N=2" in source


def test_deploy_production_prunes_after_smoke_and_on_skipped_sha() -> None:
    """Prune is a sibling job: after smoke, or when exact-SHA deploy is skipped."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "scripts/prune_vercel_deployments.py" in workflow
    assert "--fail-soft" in workflow
    assert "needs.deploy.result == 'success'" in workflow
    assert "needs.deploy.result == 'skipped'" in workflow
    assert "vercel remove comic-pile" not in workflow
    assert workflow.index(".venv/bin/alembic upgrade head") < workflow.index("vercel deploy")
    assert workflow.index("Smoke production health") < workflow.index(
        "Prune older Vercel deployments"
    )
    assert "ref: ${{ needs.preflight.outputs.deploy_sha }}" in workflow


def test_deployment_docs_describe_keep_two_ready_policy() -> None:
    """The keep policy must be documented next to the deploy contract."""
    docs = DOCS.read_text(encoding="utf-8")

    assert "current production" in docs
    assert "previous READY production" in docs
    assert "keep-N=2" in docs
    assert "scripts/prune_vercel_deployments.py" in docs
    assert "--fail-soft" in docs

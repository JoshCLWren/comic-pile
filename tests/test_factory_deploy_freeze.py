"""Regression coverage for the Deploy Production red-run freeze."""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / ".github" / "scripts" / "factory_deploy_freeze.py"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
DEPLOY_DOCS = REPO_ROOT / "docs" / "DEPLOYMENT.md"
VERCEL_DOCS = REPO_ROOT / "docs" / "VERCEL_DEPLOYMENT.md"

RED_RUN_URL = "https://github.com/JoshCLWren/comic-pile/actions/runs/99"


def load_module() -> ModuleType:
    """Load the freeze helper from its workflow script path.

    Returns:
        Imported helper module.

    """
    spec = importlib.util.spec_from_file_location("factory_deploy_freeze", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def jobs(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    """Build job fixtures for one workflow run.

    Args:
        pairs: ``(job name, conclusion)`` tuples.

    Returns:
        Job mappings the freeze helper understands.

    """
    return [{"name": name, "conclusion": conclusion} for name, conclusion in pairs]


def attempted_jobs(*, deploy_conclusion: str = "success") -> list[dict[str, str]]:
    """Jobs for a run that got past the freeze gate.

    Args:
        deploy_conclusion: Conclusion of the migrate/deploy job.

    Returns:
        Job fixtures including a non-gate job that ran.

    """
    return jobs(
        ("Red-deploy freeze gate", "success"),
        ("Deduplicate exact main SHA", "success"),
        ("Migrate Neon and deploy exact main SHA", deploy_conclusion),
    )


def gate_blocked_jobs(*, freeze_conclusion: str = "success") -> list[dict[str, str]]:
    """Jobs for a run the freeze gate stopped before a deploy.

    Args:
        freeze_conclusion: Conclusion of the freeze job itself.

    Returns:
        Job fixtures with only the freeze gate running.

    """
    return jobs(
        ("Red-deploy freeze gate", freeze_conclusion),
        ("Deduplicate exact main SHA", "skipped"),
        ("Migrate Neon and deploy exact main SHA", "skipped"),
    )


def run(
    run_id: int,
    *,
    name: str = "Deploy Production",
    status: str = "completed",
    conclusion: str = "success",
    updated_at: str = "2026-10-12T12:00:00Z",
    html_url: str | None = None,
    job_list: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    """Build one workflow-run fixture.

    Args:
        run_id: Numeric workflow-run identifier.
        name: Workflow display name.
        status: GitHub run status.
        conclusion: Terminal workflow conclusion.
        updated_at: ISO timestamp used to pick the latest run.
        html_url: Optional HTML URL for the run.
        job_list: Optional jobs used to detect gate-blocked runs.

    Returns:
        Workflow-run fixture.

    """
    payload: dict[str, object] = {
        "conclusion": conclusion,
        "html_url": html_url or f"https://github.com/JoshCLWren/comic-pile/actions/runs/{run_id}",
        "id": run_id,
        "name": name,
        "status": status,
        "updated_at": updated_at,
    }
    if job_list is not None:
        payload["jobs"] = job_list
    return payload


def test_red_last_run_blocks_without_override() -> None:
    """A red last completed Deploy Production run freezes deploys and merges."""
    module = load_module()
    payload = {
        "workflow_runs": [
            run(
                10,
                conclusion="success",
                updated_at="2026-10-12T11:00:00Z",
                job_list=attempted_jobs(),
            ),
            run(
                99,
                conclusion="failure",
                updated_at="2026-10-12T18:00:00Z",
                html_url=RED_RUN_URL,
                job_list=attempted_jobs(deploy_conclusion="failure"),
            ),
            run(11, status="in_progress", conclusion="", updated_at="2026-10-12T19:00:00Z"),
        ]
    }

    decision = module.evaluate_freeze(payload)

    assert decision["blocked"] is True
    assert decision["frozen"] is True
    assert decision["overridden"] is False
    assert decision["run_id"] == 99
    assert decision["run_url"] == RED_RUN_URL
    assert RED_RUN_URL in str(decision["reason"])
    assert "failure" in str(decision["reason"])


def test_successful_last_run_is_all_clear() -> None:
    """A green last completed run leaves deploys and merges open."""
    module = load_module()
    payload = {
        "workflow_runs": [
            run(
                8,
                conclusion="failure",
                updated_at="2026-10-11T12:00:00Z",
                job_list=attempted_jobs(deploy_conclusion="failure"),
            ),
            run(
                9,
                conclusion="success",
                updated_at="2026-10-12T12:00:00Z",
                job_list=attempted_jobs(),
            ),
        ]
    }

    decision = module.evaluate_freeze(payload)

    assert decision["blocked"] is False
    assert decision["frozen"] is False
    assert decision["run_id"] == 9


def test_override_requires_reason_and_unblocks_red_run() -> None:
    """Override without a reason stays blocked; a reason logs and proceeds."""
    module = load_module()
    payload = {
        "workflow_runs": [
            run(
                99,
                conclusion="timed_out",
                html_url=RED_RUN_URL,
                job_list=attempted_jobs(deploy_conclusion="timed_out"),
            )
        ]
    }

    missing = module.evaluate_freeze(payload, override=True, reason="   ")
    assert missing["blocked"] is True
    assert missing["overridden"] is False
    assert "non-empty reason" in str(missing["reason"])

    allowed = module.evaluate_freeze(
        payload,
        override=True,
        reason="Hotfix for #3509 already on main",
    )
    assert allowed["blocked"] is False
    assert allowed["overridden"] is True
    assert allowed["frozen"] is False
    assert RED_RUN_URL in str(allowed["reason"])
    assert "Hotfix for #3509 already on main" in str(allowed["reason"])


def test_no_completed_runs_are_all_clear() -> None:
    """Absence of history is not a freeze."""
    module = load_module()
    decision = module.evaluate_freeze({"workflow_runs": []})
    assert decision["blocked"] is False
    assert decision["frozen"] is False
    assert decision["run_id"] is None


def test_cli_exits_one_when_frozen() -> None:
    """The workflow helper fails closed when the last run is red."""
    from unittest.mock import patch

    module = load_module()
    payload = json_dumps(
        {
            "workflow_runs": [
                run(
                    99,
                    conclusion="failure",
                    html_url=RED_RUN_URL,
                    job_list=attempted_jobs(deploy_conclusion="failure"),
                )
            ]
        }
    )
    stdout = io.StringIO()
    stderr = io.StringIO()
    with patch.object(module.sys, "stdin", io.StringIO(payload)):
        with patch.object(module.sys, "stdout", stdout):
            with patch.object(module.sys, "stderr", stderr):
                code = module.main([])
    assert code == 1
    assert RED_RUN_URL in stdout.getvalue()
    assert RED_RUN_URL in stderr.getvalue()


def test_cli_override_exits_zero() -> None:
    """Maintainer override is the only unfreeze path for a red last run."""
    from unittest.mock import patch

    module = load_module()
    payload = json_dumps(
        {
            "workflow_runs": [
                run(
                    99,
                    conclusion="failure",
                    html_url=RED_RUN_URL,
                    job_list=attempted_jobs(deploy_conclusion="failure"),
                )
            ]
        }
    )
    stdout = io.StringIO()
    with patch.object(module.sys, "stdin", io.StringIO(payload)):
        with patch.object(module.sys, "stdout", stdout):
            with patch.object(module.sys, "stderr", io.StringIO()):
                code = module.main(["--override", "--reason", "fix shipped"])
    assert code == 0
    assert "fix shipped" in stdout.getvalue()


def json_dumps(payload: object) -> str:
    """Serialize a fixture payload.

    Args:
        payload: JSON-serializable object.

    Returns:
        JSON text.

    """
    import json

    return json.dumps(payload)


def test_deploy_workflow_fails_fast_before_migrations() -> None:
    """Deploy Production evaluates the freeze before touching Neon."""
    workflow = (WORKFLOWS / "deploy-production.yml").read_text(encoding="utf-8")
    freeze = "factory_deploy_freeze.py"
    migrate = ".venv/bin/alembic upgrade head"

    assert freeze in workflow
    assert workflow.index(freeze) < workflow.index(migrate)
    assert "override_freeze:" in workflow
    assert "name: Red-deploy freeze gate" in workflow
    assert "needs: freeze" in workflow
    assert "github.repository_owner" in workflow
    assert "github.actor" in workflow
    assert "--paginate" not in workflow.split("factory_deploy_freeze.py")[0][-800:]
    assert f"per_page={load_module().RUNS_PAGE_SIZE}" in workflow
    assert "needs.freeze.outputs.proceed == 'true'" in workflow
    assert 'echo "proceed=false"' in workflow
    assert "::warning::Unable to read completed Deploy Production runs; failing open." in workflow


def test_merge_drains_respect_deploy_freeze() -> None:
    """Factory auto-merge pauses while red, except PRs labeled deploy-fix."""
    names = ("factory-ready-merge-drain.yml", "fixed-model-factory-dispatch.yml")
    for name in names:
        source = (WORKFLOWS / name).read_text(encoding="utf-8")
        assert "factory_deploy_freeze.py" in source
        assert "deploy_freeze" in source
        assert "DEPLOY_FROZEN" in source
        assert "deploy-fix" in source
        assert "--paginate --slurp" not in source.split("Check Deploy Production freeze")[1][
            :800
        ]
        assert f"per_page={load_module().RUNS_PAGE_SIZE}" in source.split(
            "Check Deploy Production freeze"
        )[1][:800]
        assert "failing open" in source
        freeze_invoke = source.split("factory_deploy_freeze.py")[1][:400]
        assert "--override" not in freeze_invoke
        assert "--fetch-jobs" in freeze_invoke


def test_runbook_documents_freeze_and_override() -> None:
    """Operators can find the freeze policy and the owner override."""
    deploy = DEPLOY_DOCS.read_text(encoding="utf-8")
    vercel = VERCEL_DOCS.read_text(encoding="utf-8")
    for text in (deploy, vercel):
        assert "override_freeze" in text
        assert "Deploy Production" in text
        assert "frozen" in text.lower() or "freeze" in text.lower()
        assert "deploy-fix" in text
        assert "repository owner" in text.lower() or "github.actor" in text


def test_gate_blocked_run_does_not_latch_or_replace_the_root_cause() -> None:
    """A freeze-gate skip after a real failure still points at the real failure."""
    module = load_module()
    payload = {
        "workflow_runs": [
            run(
                1,
                conclusion="failure",
                updated_at="2026-10-12T18:00:00Z",
                html_url=RED_RUN_URL,
                job_list=attempted_jobs(deploy_conclusion="failure"),
            ),
            run(
                2,
                conclusion="success",
                updated_at="2026-10-12T18:05:00Z",
                html_url="https://github.com/JoshCLWren/comic-pile/actions/runs/2",
                job_list=gate_blocked_jobs(),
            ),
            run(
                3,
                conclusion="failure",
                updated_at="2026-10-12T18:10:00Z",
                html_url="https://github.com/JoshCLWren/comic-pile/actions/runs/3",
                job_list=gate_blocked_jobs(freeze_conclusion="failure"),
            ),
        ]
    }

    decision = module.evaluate_freeze(payload)

    assert decision["blocked"] is True
    assert decision["run_id"] == 1
    assert decision["run_url"] == RED_RUN_URL


def test_cancelled_run_does_not_lift_the_freeze() -> None:
    """A cancelled run after a red attempted deploy leaves the freeze in place."""
    module = load_module()
    payload = {
        "workflow_runs": [
            run(
                1,
                conclusion="failure",
                updated_at="2026-10-12T18:00:00Z",
                html_url=RED_RUN_URL,
                job_list=attempted_jobs(deploy_conclusion="failure"),
            ),
            run(
                2,
                conclusion="cancelled",
                updated_at="2026-10-12T18:06:00Z",
                job_list=attempted_jobs(deploy_conclusion="cancelled"),
            ),
            run(
                3,
                conclusion="skipped",
                updated_at="2026-10-12T18:07:00Z",
            ),
        ]
    }

    decision = module.evaluate_freeze(payload)

    assert decision["blocked"] is True
    assert decision["run_id"] == 1
    assert decision["run_url"] == RED_RUN_URL


def test_success_without_job_data_does_not_lift_the_freeze() -> None:
    """A green conclusion with no jobs might be a gate skip; it must not unfreeze."""
    module = load_module()
    payload = {
        "workflow_runs": [
            run(
                1,
                conclusion="failure",
                updated_at="2026-10-12T18:00:00Z",
                html_url=RED_RUN_URL,
                job_list=attempted_jobs(deploy_conclusion="failure"),
            ),
            run(2, conclusion="success", updated_at="2026-10-12T18:05:00Z"),
        ]
    }

    decision = module.evaluate_freeze(payload)

    assert decision["blocked"] is True
    assert decision["run_id"] == 1


def test_jobs_loader_stops_after_the_latest_attempted_run() -> None:
    """Jobs are fetched newest-first only until an attempted deploy is found."""
    module = load_module()
    fetched: list[int] = []

    def loader(run_id: int) -> list[dict[str, str]]:
        fetched.append(run_id)
        if run_id == 2:
            return attempted_jobs(deploy_conclusion="failure")
        return gate_blocked_jobs()

    payload = {
        "workflow_runs": [
            run(1, conclusion="failure", updated_at="2026-10-12T17:00:00Z"),
            run(3, conclusion="success", updated_at="2026-10-12T19:00:00Z"),
            run(2, conclusion="failure", updated_at="2026-10-12T18:00:00Z", html_url=RED_RUN_URL),
        ]
    }

    decision = module.evaluate_freeze(payload, jobs_loader=loader)

    assert fetched == [3, 2]
    assert decision["blocked"] is True
    assert decision["run_id"] == 2


def test_red_without_job_data_still_freezes() -> None:
    """Unknown jobs on a red run fail closed so a real deploy failure still freezes."""
    module = load_module()
    payload = {"workflow_runs": [run(99, conclusion="failure", html_url=RED_RUN_URL)]}

    decision = module.evaluate_freeze(payload)

    assert decision["blocked"] is True
    assert decision["run_id"] == 99
    assert "deploy-fix" in str(decision["reason"])

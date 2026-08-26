"""Regression coverage for ComicPile's production-only Vercel deployment policy."""

import json
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
KNOWN_GOOD_SETUP_UV_REF = "08807647e7069bb48b6ef5acd8ec9567f424441b"


def test_vercel_git_deployments_are_disabled() -> None:
    """Production must be owned by the migration-aware GitHub workflow."""
    config = json.loads((REPOSITORY_ROOT / "vercel.json").read_text(encoding="utf-8"))

    assert config["git"]["deploymentEnabled"] is False


def test_production_workflow_migrates_before_deploying() -> None:
    """Application deployment must not bypass the production schema migration."""
    workflow = (
        REPOSITORY_ROOT / ".github" / "workflows" / "deploy-production.yml"
    ).read_text(encoding="utf-8")

    migration = ".venv/bin/alembic upgrade head"
    deployment = "vercel deploy"

    assert migration in workflow
    assert deployment in workflow
    assert workflow.index(migration) < workflow.index(deployment)
    assert "branches:\n      - main" in workflow


def test_production_workflow_reconciles_factory_merges_without_push_events() -> None:
    """Factory-token merges must still trigger migration-gated production deploys."""
    workflow = (
        REPOSITORY_ROOT / ".github" / "workflows" / "deploy-production.yml"
    ).read_text(encoding="utf-8")

    assert "workflow_run:" in workflow
    assert "Factory Ready Merge Drain" in workflow
    assert "Factory Completion Drain" in workflow
    assert "schedule:" in workflow
    assert "cron: '*/5 * * * *'" in workflow
    assert "ref: main" in workflow


def test_session_context_migration_has_unique_revision_and_complete_event_columns() -> None:
    """The production migration gate needs an unambiguous, complete schema upgrade."""
    migration = (
        REPOSITORY_ROOT
        / "alembic"
        / "versions"
        / "c85700000001_add_session_bandwidth_and_event_context.py"
    ).read_text(encoding="utf-8")
    deferred_status_migration = (
        REPOSITORY_ROOT / "alembic" / "versions" / "c85700000001_add_deferred_status.py"
    ).read_text(encoding="utf-8")

    assert 'revision: str = "c85800000001"' in migration
    assert 'revision: str = "c85700000001"' in deferred_status_migration
    assert '"recommendation_context"' in migration
    assert '"context"' in migration
    assert 'down_revision: str | Sequence[str] | None = "h9i0j1k2l3m4"' in migration


def test_production_workflow_uses_known_good_setup_uv_pin() -> None:
    """Do not restore the invalid setup-uv major-version shorthand again."""
    workflow = (
        REPOSITORY_ROOT / ".github" / "workflows" / "deploy-production.yml"
    ).read_text(encoding="utf-8")

    assert f"astral-sh/setup-uv@{KNOWN_GOOD_SETUP_UV_REF}" in workflow
    assert "astral-sh/setup-uv@v9\n" not in workflow


def test_vercel_keeps_production_static_and_api_routes_intact() -> None:
    """The deployment gate must not disturb the production frontend/API split."""
    config = json.loads((REPOSITORY_ROOT / "vercel.json").read_text(encoding="utf-8"))
    routes = config["routes"]

    assert any(route.get("src") == "/api(?:/.*)?" for route in routes)
    assert any(
        route.get("src") == "/" and route.get("dest") == "/index.html"
        for route in routes
    )
    assert any(
        route.get("src") == "/(.*)" and route.get("dest") == "/index.html"
        for route in routes
    )

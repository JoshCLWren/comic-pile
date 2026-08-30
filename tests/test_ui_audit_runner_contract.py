"""Contract tests for the self-contained rendered UI audit runner."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_root_package_exposes_self_contained_ui_audit() -> None:
    """The documented root command must delegate to the lifecycle-owning wrapper."""
    package = json.loads((ROOT / "package.json").read_text())
    assert package["scripts"]["audit:ui"] == "bash scripts/run_ui_audit.sh"


def test_ui_audit_runner_owns_start_readiness_execution_and_cleanup() -> None:
    """The wrapper must own every phase that previously required manual setup."""
    runner = (ROOT / "scripts" / "run_ui_audit.sh").read_text()
    assert 'AUDIT_API_PORT="${AUDIT_API_PORT:-8002}"' in runner
    assert 'E2E_POSTGRES_PUBLISH="${E2E_POSTGRES_PUBLISH:-5432}"' in runner
    assert 'E2E_REDIS_PUBLISH="${E2E_REDIS_PUBLISH:-6379}"' in runner
    assert "compose up -d --build" in runner
    assert 'curl --fail --silent --show-error "$AUDIT_BASE_URL/health"' in runner
    assert 'BASE_URL="$AUDIT_BASE_URL"' in runner
    assert "playwright test" in runner
    assert "compose down --volumes --remove-orphans" in runner
    assert "trap cleanup EXIT INT TERM" in runner


def test_test_compose_uses_project_scoped_names_and_canonical_api_port() -> None:
    """Parallel checkouts must not share hard-coded container identities or dependency ports."""
    compose = (ROOT / "docker-compose.test.yml").read_text()
    assert "container_name:" not in compose
    assert '127.0.0.1:${E2E_API_PORT:-8002}:8000' in compose
    assert '${E2E_POSTGRES_PUBLISH:-5437:5432}' in compose
    assert '${E2E_REDIS_PUBLISH:-6379:6379}' in compose


def test_playwright_audit_defaults_to_canonical_local_api() -> None:
    """The low-level runner and self-contained wrapper must agree by default."""
    config = (ROOT / "frontend" / "playwright.audit.config.ts").read_text()
    assert "http://127.0.0.1:8002" in config
    assert "localhost:9000" not in config


def test_required_ci_summary_includes_rendered_ui_audit() -> None:
    """A broken browser audit harness must make the required CI summary fail."""
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "  ui-audit:\n" in workflow
    assert "name: Rendered UI Audit (Chromium)" in workflow
    assert "run: pnpm run audit:ui" in workflow
    assert "needs.ui-audit.result" in workflow

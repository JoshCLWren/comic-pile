"""Guard the shared disposable database contract of the Chromium regression lane.

Issue #5119: in test mode the Python settings prefer TEST_DATABASE_URL (also
loaded from the tracked .env.test on :5437) over DATABASE_URL, while the native
Rust v2 service reads RUST_ROLL_DATABASE_URL. The scheduled workflow must pin
all three to one disposable database, otherwise the two runtimes register
fixtures in different databases and the P0 suite fails with 404/401 noise.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "e2e-chromium-regression.yml"
SKILL_PATH = REPO_ROOT / ".agents" / "skills" / "e2e-chromium-regression" / "SKILL.md"
SHARED_DB_ENV_NAMES = ("DATABASE_URL", "TEST_DATABASE_URL", "RUST_ROLL_DATABASE_URL")
SHARED_DB_HOSTS = frozenset({"127.0.0.1", "localhost"})
SHARED_DB_PORT = 5432
SHARED_DB_NAME = "comic_pile_e2e_regression"


def _load_workflow() -> dict:
    """Load the regression workflow document from disk."""
    document = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _workflow_env(document: dict) -> dict:
    """Return the workflow-level env block shared by every step."""
    env = document.get("env")
    assert isinstance(env, dict)
    return env


def _endpoint(url: str) -> tuple[str, int | None, str]:
    """Normalize a SQLAlchemy or native PostgreSQL URL to (host, port, name)."""
    parsed = urlsplit(url)
    assert parsed.hostname is not None, url
    return parsed.hostname, parsed.port, parsed.path.lstrip("/")


def test_top_level_env_pins_one_shared_database_endpoint() -> None:
    """All three runtime DB URLs resolve to the same disposable endpoint."""
    env = _workflow_env(_load_workflow())
    urls = {name: env.get(name) for name in SHARED_DB_ENV_NAMES}
    assert all(isinstance(url, str) and url for url in urls.values()), urls
    endpoints = {_endpoint(str(url)) for url in urls.values()}
    assert len(endpoints) == 1, urls
    host, port, name = endpoints.pop()
    assert host in SHARED_DB_HOSTS
    assert port == SHARED_DB_PORT
    assert name == SHARED_DB_NAME


def test_no_step_redefines_a_shared_database_url() -> None:
    """A step-level override cannot silently point one runtime at another DB."""
    document = _load_workflow()
    jobs = document.get("jobs")
    assert isinstance(jobs, dict)
    for job in jobs.values():
        assert isinstance(job, dict)
        for step in job.get("steps", []):
            assert isinstance(step, dict)
            step_env = step.get("env", {})
            assert isinstance(step_env, dict)
            for name in SHARED_DB_ENV_NAMES:
                assert name not in step_env, f"{step.get('name')} overrides {name}"


def test_regression_lane_contract_is_preserved() -> None:
    """Scheduling, dispatch inputs, permissions and test-mode guard stay intact."""
    document = _load_workflow()
    # PyYAML 1.1 parses the workflow's `on` key as boolean True.
    triggers = document.get(True, document.get("on"))
    assert isinstance(triggers, dict)
    assert triggers["schedule"][0]["cron"] == "47 4 * * *"
    assert "workflow_dispatch" in triggers
    dispatch = triggers["workflow_dispatch"]
    assert isinstance(dispatch, dict)
    inputs = dispatch["inputs"]
    assert isinstance(inputs, dict)
    assert set(inputs) == {"scope", "workers"}
    assert inputs["scope"]["default"] == "p1-p2"
    assert inputs["workers"]["default"] == "2"
    assert document["permissions"] == {"contents": "read"}
    assert _workflow_env(document)["TEST_ENVIRONMENT"] == "true"


def test_local_skill_command_pins_test_database_url() -> None:
    """The documented local backend command pins TEST_DATABASE_URL alongside DATABASE_URL."""
    skill = SKILL_PATH.read_text(encoding="utf-8")
    backend_block = next(
        block for block in skill.split("```bash") if "uvicorn app.main:app" in block
    )
    assert "DATABASE_URL=" in backend_block
    assert "TEST_DATABASE_URL=" in backend_block

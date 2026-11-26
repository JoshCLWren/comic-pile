"""Guard the Rust-only database contract of the Chromium regression lane.

Issue #5741: with no Python application runtime, the lane pins one disposable
PostgreSQL database through RUST_ROLL_DATABASE_URL alone. The retired
DATABASE_URL / TEST_DATABASE_URL pair and SQLAlchemy driver prefixes must not
reappear in the workflow, env files, or local skill instructions. The lane's
scheduling, dispatch inputs, permissions, and test-mode guard stay intact.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "e2e-chromium-regression.yml"
SKILL_PATH = REPO_ROOT / ".agents" / "skills" / "e2e-chromium-regression" / "SKILL.md"
ENV_TEST_PATH = REPO_ROOT / ".env.test"
ENV_EXAMPLE_PATH = REPO_ROOT / ".env.example"
DB_ENV_NAME = "RUST_ROLL_DATABASE_URL"
RETIRED_DB_ENV_NAMES = ("DATABASE_URL", "TEST_DATABASE_URL")
ALL_DB_ENV_NAMES = (*RETIRED_DB_ENV_NAMES, DB_ENV_NAME)
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
    """Normalize a PostgreSQL URL to (host, port, name)."""
    parsed = urlsplit(url)
    assert parsed.hostname is not None, url
    return parsed.hostname, parsed.port, parsed.path.lstrip("/")


def _bash_blocks(text: str) -> list[str]:
    """Return the contents of fenced bash blocks in a Markdown document.

    Args:
        text: Markdown source to scan.

    Returns:
        Code from each ``bash`` fence, excluding the surrounding prose.
    """
    return [segment.split("```", 1)[0] for segment in text.split("```bash")[1:]]


def _env_file_values(path: Path) -> dict[str, str]:
    """Parse the simple KEY=value env file format used by the repository.

    Args:
        path: Env file to read.

    Returns:
        Mapping of variable names to their unquoted values.
    """
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def test_workflow_pins_one_rust_database_url() -> None:
    """The lane pins exactly one plain PostgreSQL URL, via RUST_ROLL_DATABASE_URL."""
    env = _workflow_env(_load_workflow())
    for name in RETIRED_DB_ENV_NAMES:
        assert name not in env, f"{name} is a retired runtime DB pin"
    url = env.get(DB_ENV_NAME)
    assert isinstance(url, str) and url, env
    assert url.startswith("postgresql://"), url
    host, port, name = _endpoint(url)
    assert host in SHARED_DB_HOSTS
    assert port == SHARED_DB_PORT
    assert name == SHARED_DB_NAME


def test_no_step_redefines_a_database_url() -> None:
    """Neither a step override nor an alias may point one consumer at another DB."""
    document = _load_workflow()
    jobs = document.get("jobs")
    assert isinstance(jobs, dict)
    for job in jobs.values():
        assert isinstance(job, dict)
        for step in job.get("steps", []):
            assert isinstance(step, dict)
            step_env = step.get("env", {})
            assert isinstance(step_env, dict)
            for name in (*ALL_DB_ENV_NAMES, "MIGRATE_DATABASE_URL"):
                assert name not in step_env, f"{step.get('name')} overrides {name}"


def test_migrations_derive_url_from_single_rust_pin() -> None:
    """The refinery runner consumes MIGRATE_DATABASE_URL derived from the Rust pin."""
    document = _load_workflow()
    jobs = document.get("jobs")
    assert isinstance(jobs, dict)
    steps = [
        step
        for job in jobs.values()
        for step in job.get("steps", [])
        if isinstance(step, dict)
    ]
    migration = next(step for step in steps if step.get("name") == "Apply migrations")
    command = migration.get("run")
    assert isinstance(command, str)
    assert 'MIGRATE_DATABASE_URL="$RUST_ROLL_DATABASE_URL"' in command
    assert "asyncpg" not in WORKFLOW_PATH.read_text(encoding="utf-8")


def test_no_python_backend_settings_in_workflow() -> None:
    """Python backend-only settings are gone; the lane keeps its test-mode guard."""
    document = _load_workflow()
    env = _workflow_env(document)
    for name in ("ENVIRONMENT", "SECRET_KEY", "AUTO_BACKUP_ENABLED"):
        assert name not in env, name
    assert env["TEST_ENVIRONMENT"] == "true"
    assert "uvicorn" not in WORKFLOW_PATH.read_text(encoding="utf-8")


def test_regression_lane_contract_is_preserved() -> None:
    """Scheduling, dispatch inputs, permissions and the DB pin stay intact."""
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
    assert DB_ENV_NAME in _workflow_env(document)


def test_local_skill_pins_single_rust_database_url() -> None:
    """The documented local runtime starts Rust with one plain DB URL."""
    skill = SKILL_PATH.read_text(encoding="utf-8")
    blocks = _bash_blocks(skill)
    db_block = next(block for block in blocks if "E2E_TEST_DB_URL=" in block)
    assert 'E2E_TEST_DB_URL="postgresql://' in db_block
    backend_block = next(block for block in blocks if DB_ENV_NAME in block)
    assert f'{DB_ENV_NAME}="$E2E_TEST_DB_URL"' in backend_block
    assert "uvicorn app.main:app" not in backend_block
    assert "asyncpg" not in skill
    assert "TEST_DATABASE_URL=" not in skill


def test_env_files_use_plain_rust_database_urls() -> None:
    """Tracked env examples carry no retired DB pin or driver dialect."""
    for path in (ENV_TEST_PATH, ENV_EXAMPLE_PATH):
        text = path.read_text(encoding="utf-8")
        assert "asyncpg" not in text, path
        values = _env_file_values(path)
        assert RETIRED_DB_ENV_NAMES[1] not in values, path
        url = values.get(DB_ENV_NAME)
        assert isinstance(url, str) and url.startswith("postgresql://"), (path, url)
        # DATABASE_URL survives in the example only as the tooling URL (the
        # refinery runner and backup helpers), never as a runtime DB pin.
        tooling_url = values.get("DATABASE_URL")
        if tooling_url is not None:
            assert tooling_url.startswith("postgresql://"), (path, tooling_url)
    test_values = _env_file_values(ENV_TEST_PATH)
    assert "DATABASE_URL" not in test_values, ENV_TEST_PATH
    host, port, name = _endpoint(test_values[DB_ENV_NAME])
    assert host in SHARED_DB_HOSTS
    assert port == 5437
    assert name == "comic_pile_test"

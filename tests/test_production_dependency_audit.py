"""Regression coverage for the production Vercel dependency diet (issue #2841).

The Vercel Python function installs ``[project].dependencies`` from
``pyproject.toml`` without installing dependency groups. This suite locks the
audit contract: test/server/migration tooling stays out of the deployed set,
the request-path packages stay in, and every other runtime discovers the
moved tooling through the shared default groups.
"""

from __future__ import annotations

import tomllib
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _pyproject() -> dict:
    """Return the parsed root ``pyproject.toml``.

    Returns:
        Parsed TOML document for the repository's pyproject.toml.
    """
    return tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _lockfile() -> dict:
    """Return the parsed root ``uv.lock``.

    Returns:
        Parsed TOML document for the repository's uv.lock.
    """
    return tomllib.loads((REPOSITORY_ROOT / "uv.lock").read_text(encoding="utf-8"))


def _lock_project_package() -> dict:
    """Return the lockfile entry describing the ``comic-pile`` project package.

    Returns:
        The ``comic-pile`` virtual package entry from ``uv.lock``.
    """
    for package in _lockfile()["package"]:
        if package.get("name") == "comic-pile":
            return package
    raise AssertionError("uv.lock has no comic-pile project package entry")


def _project_dependency_names() -> list[str]:
    """Return normalized names of the production runtime dependency set.

    Returns:
        Lowercased, extras-stripped names declared in ``[project].dependencies``.
    """
    names: list[str] = []
    for dependency in _pyproject()["project"]["dependencies"]:
        name = dependency.split(">=", 1)[0].split("[", 1)[0].lower()
        names.append(name)
    return names


def _group_dependency_names(group: str) -> list[str]:
    """Return normalized names of a named dependency group.

    Args:
        group: Dependency group name (dev, migrate, or server).

    Returns:
        Lowercased, extras-stripped names declared in the group.
    """
    names: list[str] = []
    for dependency in _pyproject()["dependency-groups"][group]:
        name = dependency.split(">=", 1)[0].split("[", 1)[0].lower()
        names.append(name)
    return names


def test_pytest_xdist_is_not_a_production_dependency() -> None:
    """pytest-xdist must ship in the dev group only (acceptance criterion)."""
    assert "pytest-xdist" not in _project_dependency_names()
    assert "pytest-xdist" in _group_dependency_names("dev")


def test_server_tooling_is_out_of_the_vercel_runtime() -> None:
    """Uvicorn must live in the server group plus dev, not project deps."""
    project_names = _project_dependency_names()
    assert "uvicorn" not in project_names
    assert "uvicorn" in _group_dependency_names("server")
    assert "uvicorn" in _group_dependency_names("dev")


def test_migration_tooling_is_out_of_the_vercel_runtime() -> None:
    """Alembic and psycopg must live in the migrate group, not project deps."""
    project_names = _project_dependency_names()
    assert "alembic" not in project_names
    assert "psycopg" not in project_names
    assert "alembic" in _group_dependency_names("migrate")
    assert "psycopg" in _group_dependency_names("migrate")


def test_unused_jinja2_is_removed_entirely() -> None:
    """jinja2 is unused across the repo and must not appear anywhere."""
    pyproject_text = (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "jinja2" not in pyproject_text


def test_script_only_yaml_lives_in_dev_not_prod() -> None:
    """PyYAML is operator/script tooling and must stay out of project deps."""
    assert "pyyaml" not in _project_dependency_names()
    assert "pyyaml" in _group_dependency_names("dev")


def test_request_path_dependencies_are_retained() -> None:
    """Packages imported by api/index.py request-path code stay in the runtime set."""
    project_names = _project_dependency_names()
    for required in {
        "fastapi",
        "sqlalchemy",
        "asyncpg",
        "pillow",
        "pydantic",
        "pydantic-settings",
        "python-multipart",
        "python-dotenv",
        "python-jose",
        "bcrypt",
        "email-validator",
        "filelock",
        "pygithub",
        "slowapi",
        "upstash-redis",
    }:
        assert required in project_names


def test_default_groups_cover_all_non_vercel_runtimes() -> None:
    """Local dev, CI, Docker, and the deploy migration step see every group."""
    default_groups = _pyproject()["tool"]["uv"]["default-groups"]
    assert default_groups == ["dev", "migrate", "server"]


def test_lockfile_project_metadata_matches_the_slim_set() -> None:
    """uv.lock must agree with the trimmed production dependency set."""
    package = _lock_project_package()
    locked_requires = {item["name"] for item in package["metadata"]["requires-dist"]}
    for removed in {"alembic", "jinja2", "psycopg", "pytest-xdist", "pyyaml", "uvicorn"}:
        assert removed not in locked_requires

    dev_dependencies = package["dev-dependencies"]
    assert "migrate" in dev_dependencies
    assert "server" in dev_dependencies
    migrate_names = {item["name"] for item in dev_dependencies["migrate"]}
    server_names = {item["name"] for item in dev_dependencies["server"]}
    assert {"alembic", "psycopg"} <= migrate_names
    assert "uvicorn" in server_names
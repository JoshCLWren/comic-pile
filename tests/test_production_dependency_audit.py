"""Regression coverage for the retained Python dependency surface (#5431).

The Python request-serving API is deleted; the remaining Python toolchain only
supports operator/CI scripts. This suite locks that slim contract: API-only
packages stay out, script tooling stays in its group, and the migration tree
is gone.
"""

from __future__ import annotations

import re
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
    """Return normalized names of the retained runtime dependency set.

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
        group: Dependency group name (dev or migrate).

    Returns:
        Lowercased names, recursively resolving PEP 735 include-group entries.
    """
    names: list[str] = []
    for dependency in _pyproject()["dependency-groups"][group]:
        if isinstance(dependency, dict):
            assert set(dependency) == {"include-group"}
            included = dependency["include-group"]
            assert isinstance(included, str)
            names.extend(_group_dependency_names(included))
        else:
            assert isinstance(dependency, str)
            names.append(re.split(r"[<>=!~;\[\s]", dependency, maxsplit=1)[0].lower())
    return names


def test_pytest_xdist_is_dev_only() -> None:
    """pytest-xdist must ship in the dev group only."""
    assert "pytest-xdist" not in _project_dependency_names()
    assert "pytest-xdist" in _group_dependency_names("dev")


def test_python_api_dependencies_are_removed() -> None:
    """Packages that only the deleted FastAPI request path needed are gone."""
    project_names = set(_project_dependency_names())
    for removed in {
        "fastapi",
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
        "uvicorn",
    }:
        assert removed not in project_names


def test_migration_tooling_is_out_of_the_runtime() -> None:
    """Alembic is deleted; psycopg stays in the operator migrate group only."""
    project_names = set(_project_dependency_names())
    assert "alembic" not in project_names
    assert "psycopg" not in project_names
    assert "psycopg" in _group_dependency_names("migrate")
    assert not (REPOSITORY_ROOT / "alembic.ini").exists()
    assert not (REPOSITORY_ROOT / "alembic").exists()


def test_unused_jinja2_is_removed_entirely() -> None:
    """jinja2 is unused across the repo and must not appear anywhere."""
    pyproject_text = (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "jinja2" not in pyproject_text


def test_script_only_yaml_lives_in_dev_not_prod() -> None:
    """PyYAML is operator/script tooling and must stay out of project deps."""
    assert "pyyaml" not in _project_dependency_names()
    assert "pyyaml" in _group_dependency_names("dev")


def test_operator_runtime_dependencies_are_retained() -> None:
    """Libraries imported by retained scripts stay in the runtime set."""
    # comic_pile_api.py (backup/restore helpers) imports requests; it must
    # stay in [project.dependencies] or the retained script fails in production.
    assert {"sqlalchemy", "asyncpg", "httpx", "requests"} <= set(_project_dependency_names())


def test_default_groups_cover_all_non_vercel_runtimes() -> None:
    """Local dev and CI see every retained dependency group."""
    default_groups = _pyproject()["tool"]["uv"]["default-groups"]
    assert default_groups == ["dev", "migrate"]


def test_async_database_runtime_installs_greenlet_without_dev_tools() -> None:
    """SQLAlchemy async support must not depend on Playwright's dev dependency."""
    dependencies = _pyproject()["project"]["dependencies"]
    assert any(dependency.startswith("sqlalchemy[asyncio]") for dependency in dependencies)

    package = _lock_project_package()
    sqlalchemy = next(item for item in package["dependencies"] if item["name"] == "sqlalchemy")
    assert "asyncio" in sqlalchemy["extra"]
    sqlalchemy_metadata = next(
        item for item in package["metadata"]["requires-dist"] if item["name"] == "sqlalchemy"
    )
    assert "asyncio" in sqlalchemy_metadata["extras"]

    locked_sqlalchemy = next(
        item for item in _lockfile()["package"] if item["name"] == "sqlalchemy"
    )
    assert any(
        item["name"] == "greenlet" for item in locked_sqlalchemy["optional-dependencies"]["asyncio"]
    )


def test_lockfile_project_metadata_matches_the_slim_set() -> None:
    """uv.lock must agree with the trimmed production dependency set."""
    package = _lock_project_package()
    locked_requires = {item["name"] for item in package["metadata"]["requires-dist"]}
    for removed in {
        "alembic",
        "fastapi",
        "jinja2",
        "psycopg",
        "pytest-xdist",
        "pyyaml",
        "uvicorn",
    }:
        assert removed not in locked_requires

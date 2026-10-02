"""Structural guard for issue #2972: no application-cache reads on read paths.

Backend read endpoints must execute their database/service logic directly. The
cache implementation itself was deleted by issue #2974, so this module pins the
properties that keep it deleted:

1. No module under ``app/`` or ``comic_pile/`` applies the ``cached``
   decorator.
2. No module under ``app/`` or ``comic_pile/`` imports ``cached`` or ``TTL``
   from ``app.cache``.
3. The cache implementation modules named by the original allowlist are gone,
   which is what makes the guards above non-vacuous.

A fourth check keeps the removal honest: none of the de-cached read paths may
gain process-local memoization (``lru_cache``/``functools.cache``) as a
replacement layer.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCANNED_ROOTS = ("app", "comic_pile")

#: Modules that used to *be* the cache implementation. Issue #2974 deleted
#: them, so they must stay absent. Anything importing ``app.cache`` is now an
#: import of a nonexistent module, so there is no allowlist to skip.
DELETED_CACHE_INFRASTRUCTURE_MODULES = (
    "app/cache.py",
    "app/cache_generation.py",
)

#: Read paths that previously carried a ``@cached(...)`` decorator.
DECACHED_READ_PATHS = (
    "app/api/dependency.py",
    "app/api/issue.py",
    "app/api/session.py",
    "app/api/thread.py",
    "comic_pile/dependencies.py",
)


def _python_files() -> list[Path]:
    """Return every production Python file under the scanned roots."""
    files: list[Path] = []
    for root in SCANNED_ROOTS:
        files.extend(sorted((REPO_ROOT / root).rglob("*.py")))
    return files


def _relative(path: Path) -> str:
    """Return a repo-relative POSIX path for readable assertion messages."""
    return path.relative_to(REPO_ROOT).as_posix()


def _decorated_callables(tree: ast.AST) -> list[str]:
    """Return every function/class definition in ``tree`` with a decorator."""
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for decorator in node.decorator_list:
            names.append(f"{node.name}:{ast.unparse(decorator)}")
    return names


def test_no_production_module_applies_the_cached_decorator() -> None:
    """No production file may apply ``@cached(...)`` to a callable."""
    offenders: list[str] = []
    for path in _python_files():
        for entry in _decorated_callables(ast.parse(path.read_text(encoding="utf-8"))):
            name, decorator = entry.split(":", 1)
            if decorator.startswith("cached("):
                offenders.append(f"{_relative(path)} -> {name} @ {decorator}")

    assert offenders == []


def test_no_production_module_imports_from_app_cache() -> None:
    """``app.cache`` no longer exists, so no module may import from it."""
    offenders: list[str] = []
    for path in _python_files():
        relative = _relative(path)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "app.cache":
                offenders.append(f"{relative} -> from app.cache import ...")
            elif isinstance(node, ast.Import) and any(
                alias.name == "app.cache" for alias in node.names
            ):
                offenders.append(f"{relative} -> import app.cache")

    assert offenders == []


@pytest.mark.parametrize("relative", DELETED_CACHE_INFRASTRUCTURE_MODULES)
def test_cache_implementation_modules_stay_deleted(relative: str) -> None:
    """The cache implementation stays deleted, or the guards above are vacuous."""
    assert not (REPO_ROOT / relative).exists(), f"cache module was reintroduced: {relative}"


@pytest.mark.parametrize("relative", DECACHED_READ_PATHS)
def test_de_cached_read_paths_import_no_cache_primitives(relative: str) -> None:
    """Each previously cached read module no longer imports from ``app.cache``."""
    source = (REPO_ROOT / relative).read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module != "app.cache", f"{relative} still imports from app.cache"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "app.cache", f"{relative} still imports app.cache"


@pytest.mark.parametrize("relative", DECACHED_READ_PATHS)
def test_de_cached_read_paths_add_no_process_local_memoization(relative: str) -> None:
    """Removing the cache must not be replaced by ``lru_cache``/``functools.cache``."""
    tree = ast.parse((REPO_ROOT / relative).read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names]
            modules = [node.module] if isinstance(node, ast.ImportFrom) else []
            modules.extend(alias.name for alias in node.names)
            for candidate in (*names, *modules):
                assert candidate not in {"lru_cache", "cache"}, (
                    f"{relative} imports process-local memoization: {candidate}"
                )
        elif isinstance(node, ast.Attribute):
            assert node.attr not in {"lru_cache", "cache"}, (
                f"{relative} references process-local memoization: {node.attr}"
            )
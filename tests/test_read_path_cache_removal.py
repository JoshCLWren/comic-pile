"""Structural guard for issue #2972: no application-cache reads on read paths.

Backend read endpoints must execute their database/service logic directly. The
cache implementation itself is intentionally retained (a later cleanup slice
deletes it), so this module pins exactly two properties:

1. No module under ``app/`` or ``comic_pile/`` applies the ``cached``
   decorator.
2. No module outside the cache-infrastructure allowlist imports ``cached`` or
   ``TTL`` from ``app.cache``.

A third check keeps the removal honest: none of the de-cached read paths may
gain process-local memoization (``lru_cache``/``functools.cache``) as a
replacement layer.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCANNED_ROOTS = ("app", "comic_pile")

#: Modules that *are* the cache implementation rather than a read path. The
#: scope fence for this issue keeps them intact, so their own use of ``cached``
#: and ``TTL`` is legitimate and must not be flagged.
CACHE_INFRASTRUCTURE_MODULES = frozenset(
    {
        "app/cache.py",
        "app/cache_generation.py",
    }
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


def test_only_cache_infrastructure_imports_cached_or_ttl() -> None:
    """``cached``/``TTL`` stay confined to the retained cache implementation."""
    offenders: list[str] = []
    for path in _python_files():
        relative = _relative(path)
        if relative in CACHE_INFRASTRUCTURE_MODULES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module != "app.cache":
                continue
            for alias in node.names:
                if alias.name in {"cached", "TTL"}:
                    offenders.append(f"{relative} -> from app.cache import {alias.name}")

    assert offenders == []


def test_cache_infrastructure_allowlist_still_exists() -> None:
    """The allowlist must name real files, or the guard above is vacuous."""
    for relative in sorted(CACHE_INFRASTRUCTURE_MODULES):
        assert (REPO_ROOT / relative).is_file(), f"allowlisted module missing: {relative}"


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

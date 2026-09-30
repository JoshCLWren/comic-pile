"""Structural guard for issue #2973: no cache invalidation on mutation paths.

Backend writes commit their domain change and must not perform a second
cache-generation/invalidation operation afterwards. The cache provider
implementation itself is intentionally retained (a later cleanup slice
deletes it), so this module pins exactly two properties:

1. No module under ``app/`` or ``comic_pile/`` imports the mutation-facing
   invalidation helpers from ``app.cache_invalidation`` or calls the removed
   local invalidator wrappers.
2. The retained cache provider implementation modules still exist, proving
   the guard targets mutation coupling rather than the provider itself.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCANNED_ROOTS = ("app", "comic_pile")

#: Modules that *are* the cache implementation rather than a mutation path.
#: The scope fence for this issue keeps them intact, so their own use of the
#: generation primitives is legitimate and must not be flagged.
CACHE_INFRASTRUCTURE_MODULES = frozenset(
    {
        "app/cache.py",
        "app/cache_generation.py",
    }
)

#: Mutation-facing invalidation helpers removed from production call sites.
REMOVED_INVALIDATION_HELPERS = frozenset(
    {
        "invalidate_user_view",
        "invalidate_user_views",
        "invalidate_session_caches",
        "invalidate_queue_caches",
        "invalidate_dependency_caches",
        "_invalidate_issue_caches",
        "_invalidate_continuity_caches",
    }
)

#: Mutation modules that previously performed cache invalidation.
DECOUPLED_MUTATION_PATHS = (
    "app/api/roll.py",
    "app/api/roll_recovery_switch.py",
    "app/api/undo.py",
    "app/api/issue.py",
    "app/api/session.py",
    "app/api/continuity_rule.py",
    "app/api/comicvine_resolution.py",
    "app/services/roll_service.py",
    "app/services/reading_mode.py",
    "app/services/continuity.py",
    "app/services/thread_service.py",
    "app/services/queue_service.py",
    "app/services/snooze_service.py",
    "app/services/custom_cbl.py",
    "app/services/cbl_targeted_plan_adoption.py",
    "app/services/rate_service.py",
    "app/services/dependency_service.py",
    "app/services/dependency_group_service.py",
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


def test_mutation_facing_invalidation_module_is_gone() -> None:
    """The shared mutation invalidation helper module no longer exists."""
    assert not (REPO_ROOT / "app" / "cache_invalidation.py").is_file()


def test_no_production_module_imports_removed_invalidation_helpers() -> None:
    """No production file may import the mutation-facing invalidation helpers."""
    offenders: list[str] = []
    for path in _python_files():
        relative = _relative(path)
        if relative in CACHE_INFRASTRUCTURE_MODULES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module == "app.cache_invalidation":
                offenders.append(f"{relative} -> from app.cache_invalidation import ...")
            if node.module == "app.cache_generation":
                for alias in node.names:
                    if alias.name in {"invalidate_user_cache", "invalidate_user_caches"}:
                        offenders.append(
                            f"{relative} -> from app.cache_generation import {alias.name}"
                        )

    assert offenders == []


def test_no_production_module_calls_removed_invalidation_helpers() -> None:
    """No production file may call a removed invalidation helper by name."""
    offenders: list[str] = []
    for path in _python_files():
        relative = _relative(path)
        if relative in CACHE_INFRASTRUCTURE_MODULES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in REMOVED_INVALIDATION_HELPERS:
                    offenders.append(f"{relative} -> call to {func.id}()")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in REMOVED_INVALIDATION_HELPERS:
                    offenders.append(f"{relative} -> defines {node.name}()")

    assert offenders == []


def test_cache_infrastructure_allowlist_still_exists() -> None:
    """The allowlist must name real files, or the guards above are vacuous."""
    for relative in sorted(CACHE_INFRASTRUCTURE_MODULES):
        assert (REPO_ROOT / relative).is_file(), f"allowlisted module missing: {relative}"


@pytest.mark.parametrize("relative", DECOUPLED_MUTATION_PATHS)
def test_decoupled_mutation_paths_reference_no_cache_invalidation(relative: str) -> None:
    """Each previously invalidating mutation module is free of invalidation work."""
    source = (REPO_ROOT / relative).read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module != "app.cache_invalidation", (
                f"{relative} still imports app.cache_invalidation"
            )
            if node.module == "app.cache_generation":
                for alias in node.names:
                    assert alias.name not in {"invalidate_user_cache", "invalidate_user_caches"}, (
                        f"{relative} still imports generation invalidator {alias.name}"
                    )
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                assert func.id not in REMOVED_INVALIDATION_HELPERS, (
                    f"{relative} still calls {func.id}()"
                )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.name not in REMOVED_INVALIDATION_HELPERS, (
                f"{relative} still defines {node.name}()"
            )


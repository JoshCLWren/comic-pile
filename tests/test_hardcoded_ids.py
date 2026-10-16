"""Shrink-only guard against hardcoded primary-key IDs.

Issue #3767 removed two hidden couplings: tests forcing a specific primary key
with ``User(id=<int>)`` or ``user_id=<int>`` literals, and application code
hardcoding ``user_id=1``. Some legacy tests and production-migration services
still carry such literals, so this module enforces the contract as a ratchet in
the same style as ``tests/test_router_layering_conformance.py``:

- ``tests/hardcoded_ids_baseline.json`` records every current occurrence;
- any NEW ``User(id=<int>)`` / ``user_id=<int>`` literal in ``tests/`` or NEW
  ``user_id=1`` literal in ``app/`` fails these tests;
- fixing a coupling must remove its entry from the baseline, which can only
  shrink.

These tests are intentionally dependency-free so the contract can be checked
without importing the application or touching a database.
"""

import ast
import json
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = Path(__file__).resolve().parent / "hardcoded_ids_baseline.json"

#: File name of this guard, excluded from its own scan.
_GUARD_FILE_NAME = Path(__file__).name

_SCOPE_DIRECTORIES = {"app": REPOSITORY_ROOT / "app", "tests": REPOSITORY_ROOT / "tests"}


def _named_int_arguments(node: ast.Call) -> dict[str, int]:
    """Return integer literal keyword arguments from a call node.

    Args:
        node: A call AST node to inspect.

    Returns:
        Mapping of keyword name to the integer literal value it was passed.
    """
    arguments: dict[str, int] = {}
    for keyword in node.keywords:
        if keyword.arg is None or not isinstance(keyword.value, ast.Constant):
            continue
        value = keyword.value.value
        if isinstance(value, int):
            arguments[keyword.arg] = value
    return arguments


def scan_source(source: str, *, scope: str) -> set[str]:
    """Scan one module's source for hardcoded primary-key literals.

    Args:
        source: Full Python source text of a ``tests/`` or ``app/`` module.
        scope: Either ``"tests"`` or ``"app"``, selecting which couplings to
            report.

    Returns:
        The set of offending literals, such as ``"User(id=1)"``,
        ``"user_id=7"``, or ``"user_id=1"``.

    Raises:
        ValueError: If ``scope`` is not ``"tests"`` or ``"app"``.
    """
    if scope not in _SCOPE_DIRECTORIES:
        raise ValueError(f"Unknown scan scope: {scope!r}")

    tree = ast.parse(source)
    found: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        arguments = _named_int_arguments(node)
        if scope == "tests":
            is_user_constructor = isinstance(node.func, ast.Name) and node.func.id == "User"
            if is_user_constructor and arguments.get("id", 0) > 0:
                found.add(f"User(id={arguments['id']})")
            if "user_id" in arguments:
                found.add(f"user_id={arguments['user_id']}")
        elif arguments.get("user_id") == 1:
            found.add("user_id=1")

    return found


def _scope_files(scope: str) -> list[Path]:
    """List the Python modules that participate in one scan scope.

    Args:
        scope: Either ``"tests"`` or ``"app"``.

    Returns:
        Sorted module paths, excluding this guard's own file.
    """
    directory = _SCOPE_DIRECTORIES[scope]
    paths = sorted(directory.rglob("*.py"))
    if scope == "tests":
        paths = [path for path in paths if path.name != _GUARD_FILE_NAME]
    return paths


def current_hardcoded_ids() -> dict[str, dict[str, list[str]]]:
    """Compute today's hardcoded-ID literals across ``tests/`` and ``app/``.

    Returns:
        Mapping of scope to a mapping of repository-relative module path to the
        sorted literals it contains.
    """
    violations: dict[str, dict[str, list[str]]] = {}
    for scope in _SCOPE_DIRECTORIES:
        per_scope: dict[str, list[str]] = {}
        for path in _scope_files(scope):
            found = scan_source(path.read_text(encoding="utf-8"), scope=scope)
            if found:
                per_scope[str(path.relative_to(REPOSITORY_ROOT))] = sorted(found)
        violations[scope] = per_scope
    return violations


def load_baseline() -> dict[str, dict[str, list[str]]]:
    """Load the frozen baseline of tolerated hardcoded-ID literals.

    Returns:
        Mapping of scope to a mapping of module path to allowed literals.
    """
    raw = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    return raw


def test_no_new_hardcoded_ids() -> None:
    """No module may introduce a hardcoded-ID literal beyond the baseline."""
    baseline = load_baseline()
    current = current_hardcoded_ids()

    growth: dict[str, dict[str, list[str]]] = {}
    for scope, per_scope in current.items():
        allowed_scopes = baseline.get(scope, {})
        for module, literals in per_scope.items():
            allowed = set(allowed_scopes.get(module, []))
            unexpected = [literal for literal in literals if literal not in allowed]
            if unexpected:
                growth.setdefault(scope, {})[module] = unexpected

    assert not growth, (
        "New hardcoded primary-key literals were introduced; use the "
        "database-generated id (or the authenticated user id) instead of a "
        f"hardcoded literal: {growth}"
    )


def test_scanner_detects_hardcoded_ids() -> None:
    """The scanner flags hardcoded ids in synthetic test and app code."""
    test_source = (
        "user = User(id=1, username='x')\n"
        "session = ReadingSession(user_id=7)\n"
    )
    app_source = "thread = Thread(user_id=1)\n"

    assert scan_source(test_source, scope="tests") == {"User(id=1)", "user_id=7"}
    assert scan_source(app_source, scope="app") == {"user_id=1"}


def test_scanner_accepts_dynamic_ids() -> None:
    """The scanner accepts database-generated and parameterized ids."""
    dynamic_source = (
        "user = User(username='x')\n"
        "session = ReadingSession(user_id=user.id)\n"
        "thread = Thread(user_id=user_id)\n"
    )

    assert scan_source(dynamic_source, scope="tests") == set()
    assert scan_source(dynamic_source, scope="app") == set()


if __name__ == "__main__":
    test_no_new_hardcoded_ids()

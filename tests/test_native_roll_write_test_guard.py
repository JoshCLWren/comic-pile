"""Guard: every native Roll write handler needs a disposable-Postgres test.

The #4423 production 500 shipped because the suite covered auth, request shape,
lookups, and read projections but never executed the offer INSERT. This guard
requires each mounted POST module to contain a database-backed test, with a
shrink-only baseline for handlers that predate the rule or delegate their write
to an already-tested module.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SERVICE_SOURCE = REPOSITORY_ROOT / "native" / "roll-service" / "src"
LIB_SOURCE = SERVICE_SOURCE / "lib.rs"
BASELINE = REPOSITORY_ROOT / "tests" / "native_roll_write_test_baseline.json"

POST_ROUTE_RE = re.compile(
    r'\.route\(\s*"[^"]+"\s*,\s*post\(\s*(?P<module>[a-z_]+)::[a-z_]+\s*\)\s*,?\s*\)',
    re.DOTALL,
)
DB_TEST_MARKERS = ("RUST_ROLL_TEST_DATABASE_URL", "#[tokio::test]")


def _mounted_post_modules() -> set[str]:
    """Return every Rust module mounted on a POST route.

    Returns:
        Module names referenced by ``post(module::handler)`` in the router.
    """
    source = LIB_SOURCE.read_text(encoding="utf-8")
    return {match.group("module") for match in POST_ROUTE_RE.finditer(source)}


def _has_database_test(module: str) -> bool:
    """Return whether a module contains a disposable-Postgres test.

    Args:
        module: Rust module name mounted on a POST route.

    Returns:
        True when the module source references the test database and defines a
        Tokio test, which is the minimum shape of a real write-path test.
    """
    source = (SERVICE_SOURCE / f"{module}.rs").read_text(encoding="utf-8")
    return all(marker in source for marker in DB_TEST_MARKERS)


def _baseline_modules() -> dict[str, str]:
    """Return the shrink-only allowlist of modules without write tests.

    Returns:
        Mapping of module name to the documented reason it is exempt.
    """
    payload = json.loads(BASELINE.read_text(encoding="utf-8"))
    modules = payload["modules"]
    assert isinstance(modules, dict)
    return {str(name): str(reason) for name, reason in modules.items()}


def test_every_mounted_post_handler_has_a_database_test() -> None:
    """Fail when a new write handler has no DB-backed test, or a baseline is stale."""
    mounted = _mounted_post_modules()
    baseline = _baseline_modules()

    assert mounted, "router parse found no POST routes; update the guard parser"

    missing = {
        module
        for module in mounted
        if not _has_database_test(module) and module not in baseline
    }
    assert missing == set(), (
        "Native Roll POST handlers without a disposable-Postgres test: "
        f"{sorted(missing)}. Add a test that calls the real write path, not just "
        "auth/request-shape/read helpers."
    )

    stale = sorted(set(baseline) - mounted)
    assert stale == [], (
        "Baseline entries no longer mounted on POST routes; remove them: "
        f"{stale}"
    )

    now_tested = sorted(module for module in mounted if _has_database_test(module) and module in baseline)
    assert now_tested == [], (
        "These modules now have a disposable-Postgres test; remove them from "
        f"{BASELINE.name}: {now_tested}"
    )


def test_baseline_entries_document_a_reason() -> None:
    """Exemptions must be deliberate and reviewable, not empty placeholders."""
    for module, reason in _baseline_modules().items():
        assert reason.strip(), f"{module} needs a baseline reason"

"""Guard: every native Roll write handler needs a disposable-Postgres test.

The #4423 production 500 shipped because the suite covered auth, request shape,
lookups, and read projections but never executed the offer INSERT. This guard
requires each mounted POST handler to have a database-backed test that reaches
that handler's write path, with a frozen, shrink-only baseline for handlers that
predate the rule or delegate their write to an already-tested module.

POST routes that are pure read projections (a batch body with no INSERT/UPDATE/
DELETE) cannot have a write path. They must instead prove the mounted HTTP route
against the canonical app schema in ``native/roll-service/parity``.
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
    r'\.route\(\s*"[^"]+"\s*,\s*post\(\s*(?P<path>(?:[a-z_0-9]+::)*[a-z_0-9]+)\s*\)\s*,?\s*\)',
    re.DOTALL,
)
DB_TEST_MARKER = "RUST_ROLL_TEST_DATABASE_URL"

# Mounted POST handlers that are pure read projections. Each entry must stay
# free of write SQL and carry a DB-backed HTTP parity test (asserted below).
READ_ONLY_POST_HANDLERS = {
    ("reading_boundary", "reading_boundary_batch_v2"): "test_http_reading_boundaries.py",
}
WRITE_SQL_RE = re.compile(
    r"\b(?:INSERT\s+INTO|UPDATE\s+[A-Za-z_][A-Za-z0-9_]*\s+SET|DELETE\s+FROM)\b",
    re.IGNORECASE,
)


def _lib_source() -> str:
    """Return the service router source.

    Returns:
        Contents of ``src/lib.rs``.
    """
    return LIB_SOURCE.read_text(encoding="utf-8")


def _route_matches() -> list[tuple[str, str]]:
    """Return every parsed ``post(module::handler)`` occurrence.

    Returns:
        Module/handler pairs in router order, including aliases. The module is
        the module path (``auth::handlers`` or ``roll_offer``) so nested auth
        modules resolve to their real source file.
    """
    matches: list[tuple[str, str]] = []
    for match in POST_ROUTE_RE.finditer(_lib_source()):
        path = match.group("path")
        module, _, handler = path.rpartition("::")
        matches.append((module, handler))
    return matches


def _mounted_post_routes() -> set[tuple[str, str]]:
    """Return the distinct module/handler pairs mounted on POST routes.

    Returns:
        Unique pairs referenced by ``post(module::handler)`` in the router.
    """
    return set(_route_matches())


def _test_module(module: str) -> str:
    """Return only the ``#[cfg(test)]`` section of a service module.

    Args:
        module: Rust module name mounted on a POST route.

    Returns:
        Test-module source, or an empty string when the module has no tests.
    """
    source = (SERVICE_SOURCE / f"{module.replace('::', '/')}.rs").read_text(encoding="utf-8")
    marker = "#[cfg(test)]"
    if marker not in source:
        return ""
    return source[source.index(marker):]


def _tests_write_path(module: str, handler: str) -> bool:
    """Return whether the test module reaches this handler's write path.

    A DB marker alone is insufficient: ``roll_offer`` had one for a read-only
    lookup test and still shipped the broken INSERT. Require a Tokio test plus a
    direct reference to the handler or its extracted ``persist_<handler>``
    writer inside the test module.

    Args:
        module: Rust module name mounted on a POST route.
        handler: Handler function name from the route.

    Returns:
        True when the module's tests reference the handler write path.
    """
    tests = _test_module(module)
    if not tests or DB_TEST_MARKER not in tests or "#[tokio::test]" not in tests:
        return False
    # Word-boundary match so a read helper like `existing_offer(` does not
    # masquerade as a call to `offer(`.
    references = (
        rf"(?<![A-Za-z0-9_]){re.escape(handler)}\(",
        rf"(?<![A-Za-z0-9_])persist_{re.escape(handler)}\(",
    )
    return any(re.search(pattern, tests) for pattern in references)


def _baseline_modules() -> dict[str, str]:
    """Return the frozen allowlist of modules without handler write tests.

    Returns:
        Mapping of module name to the documented reason it is exempt.
    """
    payload = json.loads(BASELINE.read_text(encoding="utf-8"))
    modules = payload["modules"]
    assert isinstance(modules, dict)
    return {str(name): str(reason) for name, reason in modules.items()}


def _baseline_allowed() -> set[str]:
    """Return the frozen declaration of allowed baseline modules.

    Returns:
        Module names explicitly permitted in the baseline.
    """
    payload = json.loads(BASELINE.read_text(encoding="utf-8"))
    allowed = payload["allowed_modules"]
    assert isinstance(allowed, list)
    return {str(name) for name in allowed}


def test_router_parser_sees_every_post_call() -> None:
    """A new route syntax must fail loudly instead of silently losing coverage."""
    parsed = _route_matches()
    post_calls = _lib_source().count("post(")
    assert len(parsed) == post_calls, (
        f"Parsed {len(parsed)} POST routes but lib.rs contains {post_calls} "
        "`post(` calls. Update the guard parser instead of dropping a handler."
    )


def test_every_mounted_post_handler_has_a_write_test() -> None:
    """Fail when a mounted handler has no DB-backed write-path test."""
    mounted = _mounted_post_routes()
    baseline = _baseline_modules()

    assert mounted, "router parse found no POST routes; update the guard parser"

    missing = sorted(
        (module, handler)
        for module, handler in mounted
        if (module, handler) not in READ_ONLY_POST_HANDLERS
        and not _tests_write_path(module, handler)
        and module not in baseline
    )
    assert missing == [], (
        "Native Roll POST handlers without a disposable-Postgres write-path "
        f"test: {missing}. Add a test that calls the handler or its "
        "persist_<handler> writer, not just auth/request-shape/read helpers."
    )

    stale = sorted(set(baseline) - {module for module, _handler in mounted})
    assert stale == [], (
        "Baseline entries no longer mounted on POST routes; remove them: "
        f"{stale}"
    )

    now_tested = sorted(
        module
        for module, handler in mounted
        if _tests_write_path(module, handler) and module in baseline
    )
    assert now_tested == [], (
        "These modules now have a write-path test; remove them from "
        f"{BASELINE.name}: {now_tested}"
    )


def test_read_only_post_handlers_are_proven_by_real_schema_http_tests() -> None:
    """A read-only POST exemption needs no write SQL and a DB-backed parity test."""
    mounted = _mounted_post_routes()
    parity_root = REPOSITORY_ROOT / "native" / "roll-service" / "parity"

    for (module, handler), parity_name in sorted(READ_ONLY_POST_HANDLERS.items()):
        assert (module, handler) in mounted, (
            f"{module}::{handler} is no longer mounted; remove its read-only "
            "exemption"
        )
        source = (SERVICE_SOURCE / f"{module.replace('::', '/')}.rs").read_text(encoding="utf-8")
        production = source.split("#[cfg(test)]", 1)[0]
        assert WRITE_SQL_RE.search(production) is None, (
            f"{module} contains write SQL; a read-only POST handler must not "
            "delete or update rows"
        )
        assert ".execute(" not in production, (
            f"{module} executes a statement directly; keep the read projection "
            "on query/query_one"
        )

        parity = parity_root / parity_name
        assert parity.is_file(), (
            f"{module} is exempt from the write-path guard, so it needs "
            f"{parity.relative_to(REPOSITORY_ROOT)} proving the mounted route "
            "against the canonical schema"
        )
        parity_source = parity.read_text(encoding="utf-8")
        assert DB_TEST_MARKER in parity_source, (
            f"{parity.name} must run against RUST_ROLL_TEST_DATABASE_URL"
        )
        assert "Base.metadata.create_all" in parity_source, (
            f"{parity.name} must build the canonical app schema"
        )


def test_baseline_is_frozen_and_documented() -> None:
    """Exemptions must be enumerated explicitly and carry a reason."""
    modules = _baseline_modules()
    allowed = _baseline_allowed()

    assert set(modules) == allowed, (
        "Baseline modules and allowed_modules must match exactly; adding a new "
        "exemption has to be an explicit, reviewable change."
    )
    for module, reason in modules.items():
        assert reason.strip(), f"{module} needs a baseline reason"

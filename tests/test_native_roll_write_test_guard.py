"""Guard: every native Rust HTTP mutation needs a disposable-Postgres test.

The #4423 production 500 shipped because the suite covered auth, request shape,
lookups, and read projections but never executed the offer INSERT. This guard
requires every mounted POST/PATCH/PUT/DELETE handler to have a database-backed
test that reaches the actual write path, with a frozen, shrink-only baseline for handlers that
predate the rule or delegate their write to an already-tested module.

POST routes that are pure read projections (a batch body with no INSERT/UPDATE/
DELETE) cannot have a write path. They must instead prove the mounted HTTP route
against the canonical schema in a DB-backed Rust HTTP integration test.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SERVICE_SOURCE = REPOSITORY_ROOT / "native" / "roll-service" / "src"
LIB_SOURCE = SERVICE_SOURCE / "lib.rs"
BASELINE = REPOSITORY_ROOT / "tests" / "native_roll_write_test_baseline.json"

WRITE_ROUTE_RE = re.compile(
    r'(?:\.route\(\s*"[^"]+"\s*,\s*|\.)'
    r'(?:post|patch|put|delete)\(\s*'
    r'(?P<path>(?:[a-z_0-9]+::)*[a-z_0-9]+)\s*\)',
    re.DOTALL,
)
# A write-path test is database-backed when it reaches the disposable database.
# `test_support` is the canonical accessor and the raw env var is the legacy /
# skip-guard spelling, so accept either.  ``RUST_ROLL_PARITY_DATABASE_URL`` is
# the restricted DML-role DSN used by the canonical-schema parity suite.
DB_TEST_MARKERS = (
    "RUST_ROLL_TEST_DATABASE_URL",
    "RUST_ROLL_PARITY_DATABASE_URL",
    "test_support::database_url",
    "test_support::test_state",
    "test_support::reset_for_test",
)

# PATCH issue handler delegates its write to a transaction-bound service.
# Require the real delegation and the writer's own DB-backed mutation test.
DELEGATED_WRITE_TESTS = {
    ("issue_handler", "read_rate_issue"): ("issue_service", "persist"),
}

# Mounted POST handlers that are pure read projections. Each entry must stay
# free of write SQL and carry a DB-backed HTTP parity test (asserted below).
# Real disposable-Postgres HTTP integration tests, not exemptions. Each entry
# must prove the exact mounted method/path, a named Tokio test, database reset,
# an Axum router request, and a success assertion.
INTEGRATION_WRITE_TESTS = {
    ("tags", "create_tag"): (
        "create_tag_writes_database_row", "POST", "/api/v2/tags",
    ),
    ("tags", "update_tag"): (
        "update_tag_persists_name_and_color", "PATCH", "/api/v2/tags/{tag_id}",
    ),
    ("tags", "delete_tag"): (
        "delete_tag_cascades_assignments", "DELETE", "/api/v2/tags/{tag_id}",
    ),
    ("tags", "assign_tag"): (
        "assign_tag_inserts_assignment", "POST", "/api/v2/tags/{tag_id}/assignments",
    ),
    ("tags", "unassign_tag"): (
        "unassign_tag_removes_assignment", "DELETE",
        "/api/v2/tags/{tag_id}/assignments/{target_type}/{target_id}",
    ),
    ("tags", "bulk_assign_tag"): (
        "bulk_assign_tag_writes_unique_assignments", "POST",
        "/api/v2/tags/{tag_id}/assignment-batches",
    ),
    ("tags", "bulk_unassign_tag"): (
        "bulk_unassign_tag_removes_assignments", "POST",
        "/api/v2/tags/{tag_id}/unassignment-batches",
    ),
}


READ_ONLY_POST_HANDLERS = {
    ("reading_boundary", "reading_boundary_batch_v2"): "reading_boundary_concurrency.rs",
    ("issue_handler", "issue_cards"): "issue_cards_http.rs",
}

READ_ONLY_POST_ROUTE_EVIDENCE = {
    ("reading_boundary", "reading_boundary_batch_v2"): ("POST", "/api/v2/reading-boundaries"),
    ("issue_handler", "issue_cards"): ("POST", "/api/v2/issues/cards"),
}
WRITE_SQL_RE = re.compile(
    r"\b(?:INSERT\s+INTO|UPDATE\s+[A-Za-z_][A-Za-z0-9_]*\s+SET|DELETE\s+FROM)\b",
    re.IGNORECASE,
)
HTTP_TEST_ROOT = REPOSITORY_ROOT / "native" / "roll-service" / "tests"
# A mounted route with its concrete method, used to find DB-backed HTTP tests
# that already exercise the handler through the production router. Axum allows
# chained method routers (``get(a).delete(b)``), so parse the path and method
# calls separately instead of requiring a single ``route(path, method(fn))``
# shape.
ROUTE_PREFIX_RE = re.compile(r'\.route\(\s*"(?P<path>[^"]+)"\s*,')
ROUTE_METHOD_RE = re.compile(
    r'(?P<method>post|patch|put|delete)\(\s*'
    r'(?P<handler>(?:[a-z_0-9]+::)*[a-z_0-9]+)\s*\)'
)


def _route_shape(path: str) -> re.Pattern[str]:
    """Match a mounted route template against concrete request URIs in tests.

    ``{param}`` segments are replaced by a non-quote wildcard so a test using
    ``/api/v2/issues/7/cards`` proves the ``/api/v2/issues/{issue_id}/cards``
    route without duplicating the template in the guard.
    """
    segments = [
        r'[^"\']+' if segment.startswith("{") and segment.endswith("}") else re.escape(segment)
        for segment in path.split("/")
    ]
    return re.compile(r'"' + "/".join(segments) + r'"')


@lru_cache(maxsize=1)
def _db_backed_http_test_sources() -> dict[str, str]:
    """Return DB-backed Rust HTTP integration tests keyed by file stem."""
    sources: dict[str, str] = {}
    if not HTTP_TEST_ROOT.is_dir():
        return sources
    for path in sorted(HTTP_TEST_ROOT.glob("*.rs")):
        source = path.read_text(encoding="utf-8")
        if (
            any(marker in source for marker in DB_TEST_MARKERS)
            and "router(" in source
            and "oneshot(" in source
        ):
            sources[path.stem] = source
    return sources


@lru_cache(maxsize=1)
def _route_registrations() -> tuple[tuple[str, str, str, str], ...]:
    """Return (module, handler, method, path) for every mounted mutation."""
    source = _lib_source()
    prefixes = [(match.start(), match.group("path")) for match in ROUTE_PREFIX_RE.finditer(source)]
    registrations: list[tuple[str, str, str, str]] = []
    for match in ROUTE_METHOD_RE.finditer(source):
        preceding = [path for position, path in prefixes if position < match.start()]
        if not preceding:
            continue
        module, _, handler = match.group("handler").rpartition("::")
        registrations.append((module, handler, match.group("method").upper(), preceding[-1]))
    return tuple(registrations)


def _http_route_test_evidence(module: str, handler: str) -> tuple[str, str] | None:
    """Return (test file, method) when a DB-backed HTTP test exercises a route."""
    for route_module, route_handler, method, path in _route_registrations():
        if (route_module, route_handler) != (module, handler):
            continue
        route_re = _route_shape(path)
        for test_file, source in _db_backed_http_test_sources().items():
            if method in source and route_re.search(source):
                return test_file, method
    return None


def _lib_source() -> str:
    """Return the service router source.

    Returns:
        Contents of ``src/lib.rs``.
    """
    return LIB_SOURCE.read_text(encoding="utf-8")


def _route_matches() -> list[tuple[str, str]]:
    """Return every parsed mutating HTTP handler occurrence.

    Returns:
        Module/handler pairs in router order, including aliases.
    """
    matches: list[tuple[str, str]] = []
    for match in WRITE_ROUTE_RE.finditer(_lib_source()):
        module, _, handler = match.group("path").rpartition("::")
        matches.append((module, handler))
    return matches


def _mounted_post_routes() -> set[tuple[str, str]]:
    """Return the module/handler pairs for all mutating HTTP routes.

    Returns:
        Unique pairs referenced by ``post(module::handler)`` in the router.
    """
    return set(_route_matches())


def _resolve_handler_module(module: str, handler: str) -> str:
    """Resolve the owning Rust module for a mounted handler.

    Routes may reference handlers without a module qualifier when the router
    imports them into scope.
    """
    if module:
        return module
    definition = re.compile(rf"(?m)^\s*pub\s+(?:async\s+)?fn\s+{re.escape(handler)}\b")
    for candidate in sorted(SERVICE_SOURCE.glob("*.rs")):
        if candidate.name == "lib.rs":
            continue
        if definition.search(candidate.read_text(encoding="utf-8")):
            return candidate.stem
    return module


def _test_module(module: str) -> str:
    """Return only the ``#[cfg(test)]`` section of a service module.

    Args:
        module: Rust module name mounted on a POST route.

    Returns:
        Test-module source, or an empty string when the module has no tests.
    """
    if not module:
        return ""
    source = (SERVICE_SOURCE / f"{module.replace('::', '/')}.rs").read_text(encoding="utf-8")
    marker = "#[cfg(test)]"
    if marker not in source:
        return ""
    return source[source.index(marker):]


def _integration_tests_write_path(module: str, handler: str) -> bool:
    """Require exact-route, database-backed HTTP integration test evidence.

    The test must send the matching method/path through the production router.
    This fails closed if its route, named test, or database proof disappears.
    """
    evidence = INTEGRATION_WRITE_TESTS.get((module, handler))
    if evidence is None:
        return False
    test_name, method, route_path = evidence
    path = REPOSITORY_ROOT / "native" / "roll-service" / "tests" / f"{module}.rs"
    if not path.is_file():
        return False
    source = path.read_text(encoding="utf-8")
    route_pattern = (
        rf'\.route\(\s*"{re.escape(route_path)}"\s*,\s*'
        rf'{method.lower()}\(\s*{re.escape(module)}::{re.escape(handler)}\s*\)'
    )
    if re.search(route_pattern, _lib_source(), flags=re.DOTALL) is None:
        return False
    if not all(
        marker in source
        for marker in (
            "test_support::database_url",
            "test_support::reset_for_test",
            "router(state.clone()).oneshot(request)",
        )
    ):
        return False
    for section in re.split(r"(?m)^#\[tokio::test\]\s*$", source)[1:]:
        if re.match(rf"\s*async fn {re.escape(test_name)}\(\)", section):
            return all(
                required in section
                for required in (
                    "mutation(",
                    f'"{method}"',
                    f'"{route_path}"',
                    "StatusCode::OK",
                )
            )
    return False


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
    resolved_module = _resolve_handler_module(module, handler)
    delegate = DELEGATED_WRITE_TESTS.get((module, handler)) or DELEGATED_WRITE_TESTS.get(
        (resolved_module, handler)
    )
    if delegate is not None:
        writer_module, writer = delegate
        if not resolved_module:
            return False
        production = (SERVICE_SOURCE / f"{resolved_module.replace('::', '/')}.rs").read_text(
            encoding="utf-8"
        )
        if f"{writer_module}::{writer}(" not in production.split("#[cfg(test)]", 1)[0]:
            return False
        tests = _test_module(writer_module)
        handler = writer
    else:
        if _integration_tests_write_path(module, handler) or _integration_tests_write_path(
            resolved_module, handler
        ):
            return True
        # Existing DB-backed Rust HTTP integration tests exercise the mounted
        # router through ``router(...).oneshot(...)``. Recognise them by the
        # exact method + route shape instead of demanding a separate exemption.
        if _http_route_test_evidence(resolved_module, handler) or _http_route_test_evidence(
            module, handler
        ):
            return True
        tests = _test_module(resolved_module)
    if not tests or "#[tokio::test]" not in tests:
        return False
    if not any(marker in tests for marker in DB_TEST_MARKERS):
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
    modules = payload.get("modules", {})
    assert isinstance(modules, dict)
    return {str(name): str(reason) for name, reason in modules.items()}


def _baseline_allowed() -> set[str]:
    """Return the frozen declaration of allowed baseline modules.

    Returns:
        Module names explicitly permitted in the baseline.
    """
    payload = json.loads(BASELINE.read_text(encoding="utf-8"))
    allowed = payload.get("allowed_modules", [])
    assert isinstance(allowed, list)
    return {str(name) for name in allowed}


def _baseline_handlers() -> dict[tuple[str, str], str]:
    """Return the frozen allowlist of handlers without recognized write tests.

    Some modules have mixed coverage (some handlers auto-detected, others not).
    Handler-level exemptions keep module-level baseline shrink-only semantics
    while allowing those uncovered handlers to be documented explicitly.
    """
    payload = json.loads(BASELINE.read_text(encoding="utf-8"))
    handlers = payload.get("handlers", {})
    assert isinstance(handlers, dict)
    result: dict[tuple[str, str], str] = {}
    for key, reason in handlers.items():
        module, _, handler = str(key).rpartition("::")
        assert module and handler, f"Invalid baseline handler key: {key!r}"
        result[(module, handler)] = str(reason)
    return result


def _baseline_allowed_handlers() -> set[tuple[str, str]]:
    """Return the frozen declaration of allowed baseline handlers."""
    payload = json.loads(BASELINE.read_text(encoding="utf-8"))
    allowed = payload.get("allowed_handlers", [])
    assert isinstance(allowed, list)
    result: set[tuple[str, str]] = set()
    for key in allowed:
        module, _, handler = str(key).rpartition("::")
        assert module and handler, f"Invalid baseline handler key: {key!r}"
        result.add((module, handler))
    return result


def test_router_parser_sees_every_post_call() -> None:
    """A new route syntax must fail loudly instead of silently losing coverage."""
    parsed = _route_matches()
    # Count whole Rust routing constructor tokens. A substring search would
    # mistakenly see `put(` inside unrelated code such as `.output()`.
    post_calls = len(re.findall(
        r"(?<![A-Za-z0-9_])(?:post|patch|put|delete)\s*\(",
        _lib_source(),
    ))
    assert len(parsed) == post_calls, (
        f"Parsed {len(parsed)} HTTP mutations but lib.rs contains {post_calls} "
        "post/patch/put/delete calls. Update the guard parser, not the exceptions."
    )


def test_every_mounted_post_handler_has_a_write_test() -> None:
    """Fail when a mounted mutation lacks a DB-backed write-path test."""
    mounted = _mounted_post_routes()
    baseline = _baseline_modules()

    assert mounted, "router parse found no write routes; update the guard parser"

    baseline_handlers = _baseline_handlers()
    baseline_allowed_handlers = _baseline_allowed_handlers()
    assert set(baseline_handlers) == baseline_allowed_handlers, (
        "Baseline handlers and allowed_handlers must match exactly; adding a new "
        "handler exemption has to be an explicit, reviewable change."
    )
    for (module, handler), reason in baseline_handlers.items():
        assert reason.strip(), f"{module}::{handler} needs a baseline reason"

    resolved_modules = {
        (module, handler): _resolve_handler_module(module, handler)
        for module, handler in mounted
    }
    resolved_keys = {
        (module, handler): (resolved_modules[(module, handler)], handler)
        for module, handler in mounted
    }
    missing = sorted(
        (module, handler)
        for module, handler in mounted
        if (module, handler) not in READ_ONLY_POST_HANDLERS
        and not _tests_write_path(module, handler)
        and resolved_modules[(module, handler)] not in baseline
        and module not in baseline
        and (module, handler) not in baseline_handlers
        and resolved_keys[(module, handler)] not in baseline_handlers
    )
    assert missing == [], (
        "Native Rust mutation handlers without a disposable-Postgres write-path "
        f"test: {missing}. Add a test that calls the handler or its "
        "persist_<handler> writer, not just auth/request-shape/read helpers."
    )

    mounted_module_names = {
        resolved_modules[(module, handler)]
        for module, handler in mounted
        if resolved_modules[(module, handler)]
    } | {module for module, _handler in mounted if module}
    stale = sorted(set(baseline) - mounted_module_names)
    assert stale == [], (
        "Baseline entries no longer mounted on POST routes; remove them: "
        f"{stale}"
    )

    mounted_pairs = set(mounted) | set(resolved_keys.values())
    stale_handlers = sorted(
        f"{module}::{handler}"
        for module, handler in baseline_handlers
        if (module, handler) not in mounted_pairs
    )
    assert stale_handlers == [], (
        "Baseline handler entries no longer mounted; remove them: "
        f"{stale_handlers}"
    )

    now_tested = sorted(
        {
            resolved_modules[(module, handler)]
            for module, handler in mounted
            if resolved_modules[(module, handler)] in baseline
            and _tests_write_path(module, handler)
        }
    )
    assert now_tested == [], (
        "These modules now have a write-path test; remove them from "
        f"{BASELINE.name}: {now_tested}"
    )

    now_tested_handlers = sorted(
        f"{module}::{handler}"
        for module, handler in baseline_handlers
        if _tests_write_path(module, handler)
        or _tests_write_path(*next(
            (orig for orig, resolved in resolved_keys.items() if resolved == (module, handler)),
            (module, handler),
        ))
    )
    assert now_tested_handlers == [], (
        "These handlers now have a write-path test; remove them from "
        f"{BASELINE.name}: {now_tested_handlers}"
    )


def test_read_only_post_handlers_are_proven_by_real_schema_http_tests() -> None:
    """A read-only POST exemption needs no write SQL and a DB-backed Rust HTTP test."""
    mounted = _mounted_post_routes()
    tests_root = REPOSITORY_ROOT / "native" / "roll-service" / "tests"

    for (module, handler), test_file in sorted(READ_ONLY_POST_HANDLERS.items()):
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

        integration_test = tests_root / test_file
        assert integration_test.is_file(), (
            f"{module} is exempt from the write-path guard, so it needs "
            f"{integration_test.relative_to(REPOSITORY_ROOT)} proving the mounted "
            "route against the canonical schema"
        )
        test_source = integration_test.read_text(encoding="utf-8")
        assert any(marker in test_source for marker in DB_TEST_MARKERS), (
            f"{integration_test.name} must run against the canonical PostgreSQL "
            "database (RUST_ROLL_TEST_DATABASE_URL or a test_support accessor)"
        )
        method, route_path = READ_ONLY_POST_ROUTE_EVIDENCE[(module, handler)]
        assert route_path in test_source, (
            f"{integration_test.name} must call the mounted route {route_path} "
            f"for {module}::{handler}"
        )
        assert method in test_source, (
            f"{integration_test.name} must exercise the actual {method} "
            f"{route_path} request for {module}::{handler}"
        )
        assert "router(" in test_source or "oneshot(" in test_source, (
            f"{integration_test.name} must exercise {route_path} through the "
            "mounted router"
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


def test_patch_write_is_guarded_and_proven_by_delegated_database_test() -> None:
    """An HTTP PATCH is a mutation, even when the handler delegates its SQL."""
    assert ("issue_handler", "read_rate_issue") in _mounted_post_routes()
    assert _tests_write_path("issue_handler", "read_rate_issue")


def test_missing_delegated_writer_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A mere auth test never substitutes for the actual PATCH write."""
    handler = tmp_path / "issue_handler.rs"
    handler.write_text("pub async fn read_rate_issue() { /* no write */ }\n")
    writer = tmp_path / "issue_service.rs"
    writer.write_text(
        '#[cfg(test)]\nmod tests { #[tokio::test] async fn test() { '
        'let _ = "RUST_ROLL_TEST_DATABASE_URL"; persist(); } }\n'
    )
    monkeypatch.setitem(globals(), "SERVICE_SOURCE", tmp_path)
    assert not _tests_write_path("issue_handler", "read_rate_issue")

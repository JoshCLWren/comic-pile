"""Prevent 'Rust code merged but real HTTP requests still use Python' cutovers.

The shared native Rust service's Axum routes are not automatically exposed by
Vercel. A production method/path needs BOTH a registration in the appropriate
isolated native entrypoint and a method-matched vercel.json rewrite ahead of
the Python catch-all.

"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUST_SERVICE = ROOT / "native/roll-service/src/lib.rs"
VERCEL_CONFIG = ROOT / "vercel.json"
NATIVE_INGRESSES = {
    "/api/native_roll.rs": ROOT / "api/native_roll.rs",
    "/api/native_issue.rs": ROOT / "api/native_issue.rs",
}
AXUM_CAPTURE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
VERCEL_CAPTURE = re.compile(r":([A-Za-z_][A-Za-z0-9_]*)")

# Retired Roll Skip operation. Reroll (POST /api/v2/roll/offer) replaced it, so
# no native ingress may ever publish it again.
RETIRED_RUST_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/api/v1/roll/skip"),
        ("POST", "/api/roll/skip"),
        ("POST", "/api/v1/roll/skip/:thread_id/unskip"),
        ("POST", "/api/roll/skip/:thread_id/unskip"),
    }
)
AXUM_ROUTE = re.compile(
    r'\.route\(\s*"(?P<path>/[^"]+)"\s*,\s*'
    r'(?P<handlers>(?:(?:get|post|put|patch|delete)\s*\([^)]*\)\s*\.?)+)'
)
# Axum 0.8 spells captures ``{name}``; normalize these to stable tokens.
# Vercel routes[].src is PCRE, not high-level rewrite syntax: a literal
# ``:name`` cannot match the concrete HTTP path.


def _normalized_path(path: str) -> str:
    """Return the Vercel-style capture spelling for an Axum route path."""
    return AXUM_CAPTURE.sub(r":\1", path)


def _axum_routes(source: str, *, start: str, end: str) -> set[tuple[str, str]]:
    """Read method/path registrations in the production router, not test code."""
    assert start in source, f"Missing Rust router marker: {start}"
    body = source.split(start, 1)[1].split(end, 1)[0]
    routes = set()
    for match in AXUM_ROUTE.finditer(body):
        path = _normalized_path(match.group("path"))
        methods = re.findall(r"(?:get|post|put|patch|delete)(?=\s*\()", match.group("handlers"))
        routes.update((method.upper(), path) for method in methods)
    assert routes, f"No Rust HTTP routes found after {start}"
    return routes


def _vercel_routes() -> list[dict[str, object]]:
    config = json.loads(VERCEL_CONFIG.read_text(encoding="utf-8"))
    routes = config["routes"]
    assert isinstance(routes, list)
    return routes


def _vercel_pattern(source: str) -> str:
    """Treat Vercel routes[].src as a literal PCRE pattern."""
    return source


def _destination(
    routes: list[dict[str, object]], method: str, path: str
) -> str | None:
    """Resolve the FIRST matching rewrite, including its HTTP-method filter."""
    for route in routes:
        source = route.get("src")
        if not isinstance(source, str) or re.fullmatch(_vercel_pattern(source), path) is None:
            continue
        methods = route.get("methods")
        if methods is not None:
            assert isinstance(methods, list)
            if method not in methods:
                continue
        destination = route.get("dest")
        if isinstance(destination, str):
            return destination
    return None


def _concrete_path(path: str) -> str:
    """Use a numeric owned Issue ID when checking parameterized Axum routes."""
    # First normalize Axum curly braces {thread_id} to Vercel colon syntax :thread_id
    normalized = AXUM_CAPTURE.sub(r":\1", path)
    # Then convert the colon syntax to numeric for concrete path matching
    concrete = VERCEL_CAPTURE.sub("42", normalized)
    # Verify curly braces are gone (Axum syntax converted)
    assert "{" not in concrete and "}" not in concrete, path
    return concrete


def _matching_concrete_path(source: str, template: str) -> str | None:
    """Find a real URL covered by a rewrite and the registered Axum template.

    Axum permits a named final capture to consume a literal action suffix,
    such as :apply in a single {plan_id_action} segment. Vercel's
    rewrite contains the literal suffix, while a plain numeric substitution
    lacks it. Derive the suffix from the rewrite rather than hardcode routes.
    """
    concrete = _concrete_path(template)
    if re.fullmatch(_vercel_pattern(source), concrete):
        return concrete
    suffix = re.search(r"(:[A-Za-z][A-Za-z0-9_-]*)\$", source)
    if suffix:
        candidate = concrete + suffix.group(1)
        if re.fullmatch(_vercel_pattern(source), candidate):
            return candidate
    return None


def _production_routes() -> tuple[
    set[tuple[str, str]], dict[str, set[tuple[str, str]]]
]:
    service = _axum_routes(
        RUST_SERVICE.read_text(encoding="utf-8"),
        start="pub fn router(",
        end="#[cfg(test)]",
    )
    ingresses = {
        function: _axum_routes(
            source.read_text(encoding="utf-8"),
            start="fn app() -> Router",
            end="#[tokio::main]",
        )
        for function, source in NATIVE_INGRESSES.items()
    }
    return service, ingresses


def _registered_route_matches(
    method: str, documented_path: str, registered: set[tuple[str, str]]
) -> bool:
    """Match actual routes, including literal suffixes after OpenAPI captures.

    Example: a documented `/{plan_id}:apply` is served by Axum's
    `/{plan_id_action}` segment. Do not hardcode which route family owns it.
    """
    normalized = _normalized_path(documented_path)
    if (method, normalized) in registered:
        return True
    concrete = AXUM_CAPTURE.sub("42", documented_path)
    for registered_method, template in registered:
        if method != registered_method:
            continue
        route_pattern = re.sub(
            r":[A-Za-z_][A-Za-z0-9_]*",
            "[^/]+",
            re.escape(template),
        )
        if re.fullmatch(route_pattern, concrete):
            return True
    return False


def test_native_openapi_matches_registered_rust_operations() -> None:
    """Derive route coverage from live Rust routers, not a handwritten endpoint list.

    Every documented method/path must be registered in the production service
    and its ingress. Every public v2 service operation must be documented,
    except the health and internal maintenance probes, which deliberately
    have separate runtime contracts.
    """
    document = json.loads(
        (ROOT / "native/contracts/v2-runtime.openapi.json").read_text(encoding="utf-8")
    )
    paths = document["paths"]
    assert isinstance(paths, dict) and paths
    documented = {
        (method.upper(), path)
        for path, methods in paths.items()
        for method in methods
    }
    service, ingresses = _production_routes()
    exposed = set().union(*ingresses.values())
    missing_service = {
        (method, path)
        for method, path in documented
        if not _registered_route_matches(method, path, service)
    }
    missing_ingress = {
        (method, path)
        for method, path in documented
        if not _registered_route_matches(method, path, exposed)
    }
    assert not missing_service, (
        f"OpenAPI operations without a Rust handler: {sorted(missing_service)}"
    )
    assert not missing_ingress, (
        f"OpenAPI operations without a native ingress: {sorted(missing_ingress)}"
    )

    # Health and the internal maintenance drain are implemented directly,
    # but do not belong to the public API contract.
    internal = {
        ("GET", "/api/v2/health"),
        ("GET", "/api/v2/maintenance/comicvine-metadata-repairs"),
    }
    public_v2 = {
        (method, path)
        for method, path in service
        if path.startswith("/api/v2/") and (method, path) not in internal
    }
    documented_v2 = {
        (method, path)
        for method, path in documented
        if path.startswith("/api/v2/")
    }
    undocumented = {
        (method, path)
        for method, path in public_v2
        if not any(
            documented_method == method
            and _registered_route_matches(method, documented_path, {(method, path)})
            for documented_method, documented_path in documented_v2
        )
    }
    assert not undocumented, f"Native v2 handlers missing OpenAPI: {sorted(undocumented)}"


def test_every_cutover_rust_handler_has_native_public_http_ingress() -> None:
    """Every service route requires an exposed method and an exact native target."""
    service, ingresses = _production_routes()
    vercel = _vercel_routes()
    public_service = {route for route in service if route[1].startswith("/api/")}
    assert any(path.endswith("/roll/bootstrap") for _, path in public_service)

    for method, path in sorted(public_service):
        owners = [
            function
            for function, routes in ingresses.items()
            if (method, path) in routes
        ]
        assert len(owners) == 1, (
            f"{method} {path} must have exactly one native Rust ingress; "
            f"found {owners!r}"
        )
        actual = _destination(vercel, method, _concrete_path(path))
        assert actual == owners[0], (
            f"{method} {path} exists in the Rust service, but Vercel sends "
            f"its real URL to {actual!r}, not {owners[0]!r}"
        )

    # A retired route must never come back: not in the Rust service, not in
    # either native ingress, and never rewritten to a native destination.
    for method, path in sorted(RETIRED_RUST_ROUTES):
        assert (method, path) not in public_service, (
            f"{method} {path} is retired; remove its Rust service route"
        )
        for function, routes in ingresses.items():
            assert (method, path) not in routes, (
                f"{method} {path} is retired; remove its {function} ingress route"
            )
        # Retired URLs now reach Rust's default JSON 404. The guard must
        # prohibit an explicit native handler, not the intentional Rust fallback.
        explicit_native = [
            route
            for route in vercel
            if route.get("dest") in NATIVE_INGRESSES
            and route.get("src") != "/api(?:/.*)?"
            and (
                not (methods := route.get("methods"))
                or (isinstance(methods, list) and method in methods)
            )
            and isinstance(route.get("src"), str)
            and re.fullmatch(str(route["src"]), _concrete_path(path))
        ]
        assert not explicit_native, (
            f"{method} {path} is retired; remove explicit native rewrites"
        )
        assert _destination(vercel, method, _concrete_path(path)) == "/api/native_roll.rs"


def test_native_vercel_rewrites_target_registered_rust_http_methods() -> None:
    """Both native entrypoints must register the method and path sent by Vercel."""
    service, ingresses = _production_routes()
    for route in _vercel_routes():
        function = route.get("dest")
        if not isinstance(function, str) or function not in ingresses:
            continue
        source = route.get("src")
        if source == "/api(?:/.*)?":
            # Default Rust ingress deliberately handles unregistered paths
            # and methods, so it is not a one-to-one Axum route mapping.
            assert function == "/api/native_roll.rs"
            assert "methods" not in route
            continue
        assert isinstance(source, str) and re.search(r"/:[A-Za-z_]", source) is None, (
            f"Vercel routes[].src must use regex, not :param: {source}"
        )
        methods = route.get("methods")
        assert isinstance(source, str) and (
            source.startswith("/api/") or source.startswith("^/api/")
        )
        assert isinstance(methods, list) and methods, (
            f"Native rewrite {source} must specify its allowed HTTP methods"
        )
        for method in methods:
            matching_ingress = {
                (registered_method, path)
                for registered_method, path in ingresses[function]
                if registered_method == method
                and _matching_concrete_path(source, path) is not None
            }
            # A parameter rewrite can legitimately also match a literal
            # sibling (for example /custom-cbls/{list_id} and /issue-search).
            # Axum chooses the static sibling, but both must land in the same
            # native entrypoint on the first matching Vercel rewrite.
            assert matching_ingress, (
                f"Vercel sends {method} {source} to {function}, "
                "but that entrypoint has no matching registered Rust route"
            )
            for registered_method, path in matching_ingress:
                concrete = _matching_concrete_path(source, path)
                assert concrete is not None
                actual = _destination(routes, registered_method, concrete)
                assert actual == function, (
                    f"Vercel sends {registered_method} {path} to {actual!r}, "
                    f"not the expected {function!r}"
                )
            if "/api/_native_" not in source:
                assert matching_ingress <= service, (
                    f"Vercel sends {method} {source} to {function}, "
                    "but the shared native Rust service does not register it"
                )


def test_axum_action_capture_matches_literal_vercel_suffix() -> None:
    """Single capture contains the action suffix rather than dropping it."""
    template = "/api/v2/example/{plan_id_action}"
    pattern = r"^/api/v2/example/[^/]+:apply$"
    assert _matching_concrete_path(pattern, template) == "/api/v2/example/42:apply"
    assert _matching_concrete_path(r"^/api/v2/example/[^/]+:publish$", template) == (
        "/api/v2/example/42:publish"
    )
    assert _matching_concrete_path(r"^/api/v2/other/[^/]+:apply$", template) is None


def test_issue_patch_uses_numeric_public_route_and_only_its_native_entrypoint() -> None:
    """Wrong methods, missing IDs, and probe routes must not invoke the Issue writer."""
    routes = _vercel_routes()
    issue = "/api/native_issue.rs"
    assert _destination(routes, "PATCH", "/api/v2/issues/42") == issue
    assert _destination(routes, "PATCH", "/api/v2/issues/101") == issue
    assert _destination(routes, "POST", "/api/v2/issues/cards") == issue
    assert _destination(routes, "GET", "/api/_native_issue/health") == issue
    for method, path in (
        ("GET", "/api/v2/issues/42"),
        ("POST", "/api/v2/issues/42"),
        ("PATCH", "/api/v2/issues/not-an-id"),
        ("GET", "/api/v2/issues/cards"),
        ("PATCH", "/api/v2/issues/cards"),
        ("POST", "/api/_native_issue/health"),
    ):
        assert _destination(routes, method, path) != issue, (method, path)


def test_axum_08_captures_normalize_to_vercel_parameters() -> None:
    """Parameterized Rust routes stay covered instead of vanishing from the guard."""
    routes = _axum_routes(
        'pub fn router(state: Arc<AppState>) -> Router { Router::new() '
        '.route("/api/v2/queue-entries/{thread_id}", get(handler)) } '
        "#[cfg(test)]",
        start="pub fn router(",
        end="#[cfg(test)]",
    )
    # This test validates that the _axum_routes function correctly normalizes
    # Axum routes from curly brace syntax ({thread_id}) to colon syntax (:thread_id),
    # which is the expected intermediate step in the route normalization process.
    # The actual vercel.json routes use regex patterns like [0-9]+$ for numeric matching.
    assert routes == {("GET", "/api/v2/queue-entries/:thread_id")}

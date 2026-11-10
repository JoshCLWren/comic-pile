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
        (method.upper(), _normalized_path(path))
        for path, methods in paths.items()
        for method in methods
    }
    service, ingresses = _production_routes()
    exposed = set().union(*ingresses.values())
    assert documented <= service, (
        f"OpenAPI operations without a Rust handler: {sorted(documented - service)}"
    )
    assert documented <= exposed, (
        f"OpenAPI operations without a native ingress: {sorted(documented - exposed)}"
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
    assert public_v2 == documented_v2, (
        f"Missing v2 OpenAPI: {sorted(public_v2 - documented_v2)}; "
        f"undelivered v2 OpenAPI: {sorted(documented_v2 - public_v2)}"
    )


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
                and re.fullmatch(_vercel_pattern(source), _concrete_path(path))
            }
            assert len(matching_ingress) == 1, (
                f"Vercel sends {method} {source} to {function}, "
                f"but that entrypoint has {len(matching_ingress)} matching routes"
            )
            if "/api/_native_" not in source:
                assert matching_ingress <= service, (
                    f"Vercel sends {method} {source} to {function}, "
                    "but the shared native Rust service does not register it"
                )


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

"""Prevent 'Rust code merged but real HTTP requests still use Python' cutovers.

The shared native Rust service's Axum routes are not automatically exposed by
Vercel. A production method/path needs BOTH a registration in the appropriate
isolated native entrypoint and a method-matched vercel.json rewrite ahead of
the Python catch-all.

The two Skip handlers were already staged in the shared Rust library without
native ingress before this guard was added. Keep them explicitly allowlisted
until the Skip cutover PR wires them, then remove those entries.
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
AXUM_CAPTURE = re.compile(r"\{[A-Za-z_][A-Za-z_0-9]*\}")

# Rust-only handlers already present on main, but NOT yet publicly cut over.
# A new endpoint must not be added here as a shortcut around live verification.
STAGED_RUST_ROUTES = frozenset(
    {
        ("POST", "/api/v1/roll/skip"),
        ("POST", "/api/roll/skip"),
    }
)
AXUM_ROUTE = re.compile(
    r'\.route\(\s*"(?P<path>/[^"]+)"\s*,\s*'
    r'(?P<method>get|post|put|patch|delete)\s*\('
)
# Axum 0.8 spells captures ``{name}``; Vercel rewrites spell them ``:name``.
# Normalize both parser outputs to the Vercel form so the ingress/rewrite
# comparisons stay exact instead of silently skipping parameterized routes.
AXUM_CAPTURE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _normalized_path(path: str) -> str:
    """Return the Vercel-style capture spelling for an Axum route path."""
    return AXUM_CAPTURE.sub(r":\1", path)


def _axum_routes(source: str, *, start: str, end: str) -> set[tuple[str, str]]:
    """Read method/path registrations in the production router, not test code."""
    assert start in source, f"Missing Rust router marker: {start}"
    body = source.split(start, 1)[1].split(end, 1)[0]
    routes = {
        (match.group("method").upper(), _normalized_path(match.group("path")))
        for match in AXUM_ROUTE.finditer(body)
    }
    assert routes, f"No Rust HTTP routes found after {start}"
    return routes


def _vercel_routes() -> list[dict[str, object]]:
    config = json.loads(VERCEL_CONFIG.read_text(encoding="utf-8"))
    routes = config["routes"]
    assert isinstance(routes, list)
    return routes


def _destination(
    routes: list[dict[str, object]], method: str, path: str
) -> str | None:
    """Resolve the FIRST matching rewrite, including its HTTP-method filter."""
    for route in routes:
        source = route.get("src")
        if not isinstance(source, str) or re.fullmatch(source, path) is None:
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
    concrete = AXUM_CAPTURE.sub("42", path)
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


def test_every_cutover_rust_handler_has_native_public_http_ingress() -> None:
    """Every service route requires an exposed method and an exact native target."""
    service, ingresses = _production_routes()
    vercel = _vercel_routes()
    public_service = {route for route in service if route[1].startswith("/api/")}
    assert any(path.endswith("/roll/bootstrap") for _, path in public_service)

    for method, path in sorted(public_service - STAGED_RUST_ROUTES):
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

    for method, path in sorted(public_service & STAGED_RUST_ROUTES):
        assert _destination(vercel, method, _concrete_path(path)) not in NATIVE_INGRESSES, (
            f"{method} {path} is now routed to Rust: remove its explicit "
            "STAGED_RUST_ROUTES exception and verify its cutover"
        )


def test_native_vercel_rewrites_target_registered_rust_http_methods() -> None:
    """Both native entrypoints must register the method and path sent by Vercel."""
    service, ingresses = _production_routes()
    for route in _vercel_routes():
        function = route.get("dest")
        if not isinstance(function, str) or function not in ingresses:
            continue
        source = route.get("src")
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
                and re.fullmatch(source, _concrete_path(path))
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
    assert routes == {("GET", "/api/v2/queue-entries/:thread_id")}

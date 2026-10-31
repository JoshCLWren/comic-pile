"""Prevent 'Rust code merged but real HTTP requests still use Python' cutovers.

The native Roll service's Axum routes are not automatically exposed by Vercel.
A production method/path needs BOTH an outer api/native_roll.rs route and a
method-matched vercel.json rewrite ahead of the Python catch-all.

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
RUST_INGRESS = ROOT / "api/native_roll.rs"
VERCEL_CONFIG = ROOT / "vercel.json"
NATIVE_FUNCTION = "/api/native_roll.rs"

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


def _axum_routes(source: str, *, start: str, end: str) -> set[tuple[str, str]]:
    """Read method/path registrations in the production router, not test code."""
    assert start in source, f"Missing Rust router marker: {start}"
    body = source.split(start, 1)[1].split(end, 1)[0]
    routes = {
        (match.group("method").upper(), match.group("path"))
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


def _production_routes() -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    service = _axum_routes(
        RUST_SERVICE.read_text(encoding="utf-8"),
        start="pub fn router(",
        end="#[cfg(test)]",
    )
    ingress = _axum_routes(
        RUST_INGRESS.read_text(encoding="utf-8"),
        start="fn app() -> Router",
        end="#[tokio::main]",
    )
    return service, ingress


def test_every_cutover_rust_handler_has_native_public_http_ingress() -> None:
    """A Rust service handler without a rewrite is NOT a completed cutover."""
    service, ingress = _production_routes()
    vercel = _vercel_routes()
    public_service = {route for route in service if route[1].startswith("/api/")}
    assert any(path.endswith("/roll/bootstrap") for _, path in public_service)

    for method, path in sorted(public_service - STAGED_RUST_ROUTES):
        assert (method, path) in ingress, (
            f"{method} {path} exists in Rust service but api/native_roll.rs "
            "does not expose it"
        )
        actual = _destination(vercel, method, path)
        assert actual == NATIVE_FUNCTION, (
            f"{method} {path} exists in Rust but real production ingress "
            f"still routes to {actual!r}, not {NATIVE_FUNCTION}"
        )

    for method, path in sorted(public_service & STAGED_RUST_ROUTES):
        assert _destination(vercel, method, path) != NATIVE_FUNCTION, (
            f"{method} {path} is now routed to Rust: remove its explicit "
            "STAGED_RUST_ROUTES exception and verify its cutover"
        )


def test_native_vercel_rewrites_target_registered_rust_http_methods() -> None:
    """An ingress rewrite alone cannot prove the Rust app accepts the request."""
    service, ingress = _production_routes()
    for route in _vercel_routes():
        if route.get("dest") != NATIVE_FUNCTION:
            continue
        source = route.get("src")
        methods = route.get("methods")
        assert isinstance(source, str) and source.startswith("/api/")
        assert isinstance(methods, list) and methods, (
            f"Native rewrite {source} must specify its allowed HTTP methods"
        )
        for method in methods:
            assert (method, source) in ingress, (
                f"Vercel sends {method} {source} to Rust, "
                "but api/native_roll.rs does not register that operation"
            )
            if not source.startswith("/api/_native_roll/"):
                assert (method, source) in service, (
                    f"Vercel sends {method} {source} to Rust, "
                    "but the native Roll service does not register it"
                )

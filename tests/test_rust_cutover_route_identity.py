"""Guard HTTP API version identity separately from implementation language.

A Rust cutover replaces one existing method/path in place. These assertions are
an intentional snapshot of the client URLs and current deployment router.
Update the *runtime map* in the PR that changes a route's implementation, after
verifying the same URL reaches Rust. Do not change a client URL merely to find
a Rust handler on a different API version.

Static wiring checks are necessary but not proof of real production execution:
#4335 also requires a successful authenticated request and native telemetry.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_SERVICES = ROOT / "frontend" / "src" / "services"
VERCEL_CONFIG = ROOT / "vercel.json"


@dataclass(frozen=True)
class _VercelRoute:
    """One validated entry from the ``routes`` array in ``vercel.json``.

    ``src`` is ``None`` for non-matching entries such as ``handle: filesystem``.
    """

    src: str | None
    dest: str | None
    methods: tuple[str, ...]


def _service(name: str) -> str:
    return (FRONTEND_SERVICES / name).read_text(encoding="utf-8")


def _json_object(value: object, context: str) -> dict[str, object]:
    """Return ``value`` as a JSON object, rejecting any other JSON shape."""
    if not isinstance(value, dict):
        raise AssertionError(f"{context} must be a JSON object, got {type(value).__name__}")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise AssertionError(f"{context} contains a non-string key")
        result[key] = item
    return result


def _load_routes() -> list[_VercelRoute]:
    """Decode and validate ``vercel.json`` routing instead of trusting its shape."""
    document = _json_object(
        json.loads(VERCEL_CONFIG.read_text(encoding="utf-8")),
        "vercel.json",
    )
    raw_routes = document.get("routes")
    if not isinstance(raw_routes, list):
        raise AssertionError("vercel.json must define a routes array")

    routes: list[_VercelRoute] = []
    for index, raw_route in enumerate(raw_routes):
        context = f"vercel.json routes[{index}]"
        route = _json_object(raw_route, context)
        src = route.get("src")
        if src is not None and not isinstance(src, str):
            raise AssertionError(f"{context}.src must be a string when present")
        dest = route.get("dest")
        if dest is not None and not isinstance(dest, str):
            raise AssertionError(f"{context}.dest must be a string when present")

        methods: list[str] = []
        raw_methods = route.get("methods")
        if raw_methods is not None:
            if not isinstance(raw_methods, list):
                raise AssertionError(f"{context}.methods must be an array when present")
            for raw_method in raw_methods:
                if not isinstance(raw_method, str):
                    raise AssertionError(f"{context}.methods entries must be strings")
                methods.append(raw_method)

        routes.append(_VercelRoute(src=src, dest=dest, methods=tuple(methods)))
    return routes


def _route_destination(method: str, path: str) -> str:
    """Resolve the first matching Vercel route, respecting HTTP method."""
    # ``src`` entries are Vercel path patterns (e.g. "/api(?:/.*)?"), so match
    # the whole path as the platform does rather than comparing raw strings.
    for route in _load_routes():
        if route.src is None or re.fullmatch(route.src, path) is None:
            continue
        if route.methods and method not in route.methods:
            continue
        if route.dest is not None:
            return route.dest
    raise AssertionError(f"Missing production routing for {method} {path}")


def _count_client_url(source: str, url: str) -> int:
    """Count client calls to ``url`` without depending on the quote style used."""
    return len(re.findall(rf"""['"`]{re.escape(url)}['"`]""", source))


def test_roll_primary_and_recovery_call_owner_approved_native_v2_contract() -> None:
    """Roll GET is deliberately consolidated to native v2; all POST paths remain v1."""
    primary = _service("rollBootstrapApi.ts")
    recovery = _service("protectedRollMutationApi.ts")

    # Both ordinary/with-timezone calls and the recovery path are real users.
    assert _count_client_url(primary, "/v2/roll/bootstrap") == 2
    assert _count_client_url(recovery, "/v2/roll/bootstrap") == 1
    assert "/v1/roll/bootstrap" not in primary
    assert "/v1/roll/bootstrap" not in recovery


def test_reading_boundaries_client_preserves_its_distinct_api_v2_contract() -> None:
    """A v2 URL is no more intrinsically Rust than a v1 URL is Python."""
    source = _service("api-reading-boundaries.ts")
    assert "client.post<Batch, { thread_ids: number[] }>(" in source
    assert "'/v2/reading-boundaries'" in source
    assert "'/v1/reading-boundaries'" not in source


def test_current_runtime_routing_is_explicit_and_independent_of_version() -> None:
    """Snapshot of *routing*, not a declaration that v1 means Python.

    Bootstrap GET has the owner-approved v2-only exception (#4350), while
    other endpoints retain independent same-path implementation migrations.
    The v1 GET Python route remains temporarily until production v2 proof
    and the immediate follow-up Python deletion PR.
    """
    expected = {
        ("GET", "/api/v1/roll/bootstrap"): "/api/index.py",
        ("GET", "/api/roll/bootstrap"): "/api/index.py",
        ("POST", "/api/v1/roll/"): "/api/index.py",
        ("GET", "/api/v2/roll/bootstrap"): "/api/native_roll.rs",
        ("POST", "/api/v2/reading-boundaries"): "/api/native_roll.rs",
    }
    for (method, path), destination in expected.items():
        actual = _route_destination(method, path)
        assert actual == destination, (
            f"{method} {path} currently routes to {actual}, expected "
            f"{destination}; if an endpoint was cut over, update this "
            "runtime snapshot in that endpoint's verified cutover PR"
        )

    # GET being native must not imply POST on that same v2 path is native.
    assert _route_destination("POST", "/api/v2/roll/bootstrap") == "/api/index.py"

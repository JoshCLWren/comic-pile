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
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_SERVICES = ROOT / "frontend" / "src" / "services"


def _service(name: str) -> str:
    return (FRONTEND_SERVICES / name).read_text(encoding="utf-8")


def _route_destination(method: str, path: str) -> str:
    """Resolve the first matching Vercel route, respecting HTTP method."""
    config: dict[str, Any] = json.loads(
        (ROOT / "vercel.json").read_text(encoding="utf-8")
    )
    for route in config["routes"]:
        pattern = route.get("src")
        if not isinstance(pattern, str):
            continue
        if re.fullmatch(pattern, path) is None:
            continue
        if method not in route.get("methods", [method]):
            continue
        destination = route.get("dest")
        if isinstance(destination, str):
            return destination
    raise AssertionError(f"Missing production routing for {method} {path}")


def test_roll_primary_and_recovery_call_original_api_v1_contract() -> None:
    """Roll bootstrap stays on its existing URL through the Python→Rust port."""
    primary = _service("rollBootstrapApi.ts")
    recovery = _service("protectedRollMutationApi.ts")

    # Both ordinary/with-timezone calls and the recovery path are real users.
    assert primary.count("'/v1/roll/bootstrap'") == 2
    assert recovery.count("'/v1/roll/bootstrap'") == 1
    assert "/v2/roll/bootstrap" not in primary
    assert "/v2/roll/bootstrap" not in recovery


def test_reading_boundaries_client_preserves_its_distinct_api_v2_contract() -> None:
    """A v2 URL is no more intrinsically Rust than a v1 URL is Python."""
    source = _service("api-reading-boundaries.ts")
    assert "client.post<Batch, { thread_ids: number[] }>(" in source
    assert "'/v2/reading-boundaries'" in source
    assert "'/v1/reading-boundaries'" not in source


def test_current_runtime_routing_is_explicit_and_independent_of_version() -> None:
    """Snapshot of *routing*, not a declaration that v1 means Python.

    When #4350 replaces GET v1 in Rust at the exact same path, update only
    that operation's expected destination here. This is deliberately a
    same-path, method-aware test so changing v1 callers to v2 cannot pass.
    """
    expected = {
        ("GET", "/api/v1/roll/bootstrap"): "/api/index.py",
        ("GET", "/api/roll/bootstrap"): "/api/index.py",
        ("POST", "/api/v1/roll/"): "/api/index.py",
        ("GET", "/api/v2/roll/bootstrap"): "/api/native_roll.rs",
        ("POST", "/api/v2/reading-boundaries"): "/api/index.py",
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

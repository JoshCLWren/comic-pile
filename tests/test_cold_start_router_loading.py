"""Route-coverage guards for per-resource deferred router loading (#3479).

``app.router_mounts`` declares which resource segments each deferred mount
serves. A missing declaration lets a real API route fall through to the JSON
404 fallback on a cold serverless start, which an eager-application test cannot
see. These guards exercise the deferred registry instead:

* every eager ``/api/*`` route is reachable after selecting mounts for its own
  path (the route-coverage guard promised by ``app.router_mounts``);
* a snooze request registers only the snooze mount, not catalog/delivery;
* ``POST /api/v1/roll/switch-prerequisite`` (composed into the dependency mount)
  answers on the first request instead of falling through to the fallback; and
* ``import api.index`` stays inside the cold-start import budget.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_app_settings
from app.main import create_app
from app.router_mounts import EAGER_SEGMENTS, build_router_mounts, request_segment, select_mounts_for_path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
API_FALLBACK_PATH = "/api/{path:path}"
PREREQUISITE_SWITCH_PATH = "/api/v1/roll/switch-prerequisite"
SNOOZE_PATH = "/api/v1/snooze/"
#: The #3479 import-time target measured on a workstation (Python 3.14, warm
#: cache). Slower runners must not fail this target, which is why the hard
#: gate is runner-relative (see the import-budget test's docstring).
IMPORT_BUDGET_MS = 600
#: The cold entry path may cost at most this multiple of the FastAPI framework
#: floor measured by the same interpreter. The pre-#3479 entry-path import
#: measured about 3.5x that floor; the deferred entry path costs about 2x.
IMPORT_FRAMEWORK_RATIO = 3.0
#: Modules a cold ``api.index`` must not pay to import (#3479). The eager
#: catalog and delivery routers and their backends (comicvine, httpx,
#: PyGithub) belong behind the per-resource deferred mounts.
FORBIDDEN_COLD_IMPORTS: tuple[str, ...] = (
    "app.api.catalog",
    "app.services.comicvine_provider",
    "httpx",
    "app.api.delivery",
    "github",
)


def _iter_effective_routes(routes, prefix: str = ""):
    """Yield ``(path, methods)`` pairs in match order.

    FastAPI 0.137+ keeps included routers as inclusion-tree nodes instead of
    flat route entries, so descend through each node's original router while
    accumulating its mount prefix.

    Args:
        routes: Route list from an application or an included router.
        prefix: Accumulated mount prefix from outer inclusion nodes.

    Yields:
        Effective route paths with their HTTP methods.
    """
    for route in routes:
        route_path = getattr(route, "path", None)
        original_router = getattr(route, "original_router", None)
        include_context = getattr(route, "include_context", None)
        nested_routes = getattr(original_router, "routes", None)
        if (
            isinstance(route_path, str)
            and not hasattr(route, "original_router")
            or nested_routes is None
            or include_context is None
        ):
            if isinstance(route_path, str):
                yield f"{prefix}{route_path}", getattr(route, "methods", None)
            continue
        nested_prefix = f"{prefix}{getattr(include_context, 'prefix', '')}"
        yield from _iter_effective_routes(nested_routes, prefix=nested_prefix)


def _route_paths(app) -> list[str]:
    """Return the application's effective route paths in match order.

    Args:
        app: FastAPI application instance.

    Returns:
        Ordered effective route paths.
    """
    return [path for path, _methods in _iter_effective_routes(app.routes)]


def _route_signatures(app) -> set[tuple[str, frozenset[str]]]:
    """Return ``(path, methods)`` signatures for the application's routes.

    Args:
        app: FastAPI application instance.

    Returns:
        Effective route signatures; method-less routes use an empty set.
    """
    return {
        (path, frozenset(methods or ()))
        for path, methods in _iter_effective_routes(app.routes)
    }


def _api_route_signatures(app) -> set[tuple[str, frozenset[str]]]:
    """Return only the eager API route signatures that mounts must cover.

    Args:
        app: FastAPI application instance.

    Returns:
        Route signatures under ``/api/`` excluding the JSON 404 fallback.
    """
    return {
        signature
        for signature in _route_signatures(app)
        if signature[0].startswith("/api/") and API_FALLBACK_PATH not in signature[0]
    }


def test_every_eager_api_route_is_reachable_from_its_selected_mounts() -> None:
    """Each path must register its owner even when mounts share a segment.

    Group by the exact selected mounts, not just the resource segment: Roll's
    prerequisite switch intentionally needs a different cold router set from
    ordinary Roll requests.
    """
    eager_signatures = _api_route_signatures(create_app(serve_frontend=False))
    assert eager_signatures

    mounts = build_router_mounts(get_app_settings().environment)
    grouped: dict[
        tuple[str, ...], tuple[str, set[tuple[str, frozenset[str]]]]
    ] = {}
    for signature in sorted(eager_signatures, key=lambda item: item[0]):
        path = signature[0]
        if request_segment(path) in EAGER_SEGMENTS:
            continue
        selected = tuple(mount.key for mount in select_mounts_for_path(path, mounts))
        if selected not in grouped:
            grouped[selected] = (path, set())
        grouped[selected][1].add(signature)

    for selected, (sample_path, expected) in grouped.items():
        app = create_app(serve_frontend=False, defer_router_imports=True)
        app.state.register_routers_for_path(sample_path)
        registered = _route_signatures(app)
        missing = sorted(expected - registered)
        assert not missing, (
            f"mounts {selected!r} for {sample_path!r} miss {missing}"
        )


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/roll/exclusions",
    ],
)
@pytest.mark.asyncio
async def test_first_roll_request_skips_dependency_subrouters(path: str) -> None:
    """A cold Roll GET needs Roll alone, not all continuity/CBL APIs.

    The Roll bootstrap GET is native Rust, so this exercises the remaining
    Python Roll GET surface to prove cold-start mount selection still isolates
    the Roll router from the dependency/CBL routers.
    """
    app = create_app(serve_frontend=False, defer_router_imports=True)
    assert PREREQUISITE_SWITCH_PATH not in _route_paths(app)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(path)

    # The Roll router answered (unauthenticated), without the dependency
    # router whose only /roll endpoint is POST switch-prerequisite.
    assert response.status_code == 401
    paths = _route_paths(app)
    assert path in paths
    assert PREREQUISITE_SWITCH_PATH not in paths

@pytest.mark.asyncio
async def test_first_snooze_request_registers_only_the_snooze_mount() -> None:
    """A cold snooze request must not import catalog or delivery."""
    eager_paths = set(_route_paths(create_app(serve_frontend=False)))
    snooze_paths = {path for path in eager_paths if request_segment(path) == "snooze"}

    app = create_app(serve_frontend=False, defer_router_imports=True)
    cold_paths = set(_route_paths(app))
    assert SNOOZE_PATH not in cold_paths

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(SNOOZE_PATH)

    # Unauthenticated: a 401 proves the snooze route answered, not the fallback.
    assert response.status_code == 401

    loaded_paths = set(_route_paths(app)) - cold_paths - {API_FALLBACK_PATH}
    assert loaded_paths
    assert loaded_paths <= snooze_paths
    assert "/api/v1/images/optimize" not in eager_paths
    for heavy_path in ("/api/v1/catalog/series", "/api/v1/delivery"):
        assert heavy_path not in cold_paths | loaded_paths


@pytest.mark.asyncio
async def test_prerequisite_switch_is_reachable_on_the_first_request() -> None:
    """The dependency-composed roll switch route must not fall through to 404."""
    app = create_app(serve_frontend=False, defer_router_imports=True)
    assert PREREQUISITE_SWITCH_PATH not in _route_paths(app)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            PREREQUISITE_SWITCH_PATH,
            json={"node_type": "issue", "node_id": 1},
        )

    assert response.status_code == 401
    assert PREREQUISITE_SWITCH_PATH in _route_paths(app)


def _importtime_modules(source: str) -> dict[str, int]:
    """Import ``source`` in a fresh interpreter and report per-module costs.

    Args:
        source: Python source executed under ``-X importtime``.

    Returns:
        Mapping from module name to cumulative import microseconds.
    """
    result = subprocess.run(
        [sys.executable, "-X", "importtime", "-c", source],
        capture_output=True,
        text=True,
        cwd=REPOSITORY_ROOT,
        check=True,
        timeout=120,
    )
    modules: dict[str, int] = {}
    for line in result.stderr.splitlines():
        if not line.startswith("import time:"):
            continue
        _self, cumulative, name = line.removeprefix("import time:").split("|", 2)
        if not cumulative.strip().isdigit():
            # CPython 3.14+ emits a column-header line before the report.
            continue
        modules[name.strip()] = int(cumulative.strip())
    return modules


def test_api_index_import_stays_within_the_cold_start_budget() -> None:
    """``import api.index`` must stay inside the cold-start import budget.

    The hard budget is runner-relative: the test measures the FastAPI
    framework floor with the same interpreter on the same machine and allows
    the cold import up to ``IMPORT_FRAMEWORK_RATIO`` times that floor. A
    fixed 600 ms wall-clock assertion flaked on GitHub Actions runners that
    import Python several times slower than a workstation (an import that
    costs about 490 ms at full speed measured 2471 ms there); the ratio stays
    stable because both measurements scale with the same interpreter and
    filesystem. Heavy cold imports are also caught structurally: the
    catalog, comicvine, images, delivery, httpx, and PyGithub top-level
    modules must not appear in the importtime report at all.
    """
    api_report = _importtime_modules("import api.index")
    assert "api.index" in api_report, "importtime did not report api.index"

    for heavy in FORBIDDEN_COLD_IMPORTS:
        assert heavy not in api_report, f"{heavy} leaks into the cold api.index import"

    framework_floor_us = _importtime_modules("import fastapi")["fastapi"]
    budget = max(IMPORT_BUDGET_MS * 1000, framework_floor_us * IMPORT_FRAMEWORK_RATIO)
    import_us = api_report["api.index"]
    assert import_us < budget, (
        f"import api.index took {import_us / 1000:.0f} ms; budget is {budget / 1000:.0f} ms "
        f"(fastapi floor {framework_floor_us / 1000:.0f} ms)"
    )

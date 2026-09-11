"""Regression proof that continuity readiness is no longer a public product surface."""

from collections.abc import Iterable

from fastapi.routing import APIRoute

from app.main import create_app


REMOVED_PATHS = {
    "/api/v1/continuity/readiness",
    "/api/v1/continuity/chains",
    "/api/v1/continuity-plans/{plan_id}/readiness",
}


def _collect_paths(routes: Iterable[object], *, prefix: str = "") -> set[str]:
    """Collect route paths across flattened and lazily included routers."""
    paths: set[str] = set()
    for route in routes:
        if isinstance(route, APIRoute):
            paths.add(f"{prefix}{route.path}")
            continue

        original_router = getattr(route, "original_router", None)
        include_context = getattr(route, "include_context", None)
        nested_routes = getattr(original_router, "routes", None)
        if nested_routes is None or include_context is None:
            continue
        nested_prefix = f"{prefix}{getattr(include_context, 'prefix', '')}"
        paths.update(_collect_paths(nested_routes, prefix=nested_prefix))
    return paths


def test_readiness_routes_are_absent_from_fastapi_and_openapi() -> None:
    """No compatibility route or generated contract may resurrect readiness."""
    app = create_app(serve_frontend=False)
    fastapi_paths = _collect_paths(app.routes)
    openapi = app.openapi()
    openapi_paths = set(openapi["paths"])

    for path in REMOVED_PATHS:
        assert path not in fastapi_paths
        assert path not in openapi_paths

    schema_names = set(openapi.get("components", {}).get("schemas", {}))
    assert not any("ContinuityReadiness" in name for name in schema_names)
    assert not any("PlanReadiness" in name for name in schema_names)

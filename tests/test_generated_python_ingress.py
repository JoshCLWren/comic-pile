"""Rust-default API ingress and automatic FastAPI route discovery regressions."""

from __future__ import annotations

import re

from fastapi import FastAPI

from scripts.generate_vercel_routes import (
    API_CATCH_ALL,
    generate_routes,
    python_operations,
    route_regex,
)


def _python_app(*, with_orphan: bool = True) -> FastAPI:
    app = FastAPI()

    @app.get("/api/v1/threads/{thread_id}")
    async def thread_detail(thread_id: int) -> dict[str, int]:
        return {"id": thread_id}

    @app.get("/api/v1/cron/release-sync", include_in_schema=False)
    async def release_sync() -> dict[str, bool]:
        return {"ok": True}

    if with_orphan:

        @app.get("/api/v1/orphan")
        async def orphan() -> dict[str, bool]:
            return {"orphan": True}

    @app.api_route("/api/{path:path}", methods=["GET"], include_in_schema=False)
    async def not_found(path: str) -> dict[str, str]:
        return {"path": path}

    return app


def _base_config() -> dict[str, object]:
    return {
        "routes": [
            {"src": "/api/v2/auth/me", "methods": ["GET"], "dest": "/api/native_roll.rs"},
            {"src": API_CATCH_ALL, "dest": "/api/index.py"},
            {"src": "/(.*)", "dest": "/index.html"},
        ]
    }


def _destination(config: dict[str, object], method: str, path: str) -> str:
    routes = config["routes"]
    assert isinstance(routes, list)
    for route in routes:
        assert isinstance(route, dict)
        src = route.get("src")
        if not isinstance(src, str) or not re.fullmatch(src, path):
            continue
        methods = route.get("methods")
        if methods is not None and method not in methods:
            continue
        dest = route.get("dest")
        if isinstance(dest, str):
            return dest
    raise AssertionError(f"No ingress for {method} {path}")


def test_raw_openapi_and_hidden_route_registration_are_both_discovered() -> None:
    """Hidden operational routes are not silently omitted from the allowlist."""
    operations = python_operations(_python_app())
    assert ("GET", "/api/v1/threads/{thread_id}") in operations
    assert ("GET", "/api/v1/cron/release-sync") in operations
    assert ("GET", "/api/v1/orphan") in operations
    assert ("GET", "/api/{path:path}") not in operations


def test_deleted_python_handler_disappears_automatically() -> None:
    """Route deletion requires no manual edits to the Vercel allowlist."""
    original = _base_config()
    before = generate_routes(original, python_operations(_python_app()))
    after = generate_routes(original, python_operations(_python_app(with_orphan=False)))

    assert _destination(before, "GET", "/api/v1/orphan") == "/api/index.py"
    assert _destination(after, "GET", "/api/v1/orphan") == "/api/native_roll.rs"
    assert _destination(after, "GET", "/api/v1/other-missing") == "/api/native_roll.rs"


def test_rust_default_and_method_specific_python_exceptions() -> None:
    """Unknown routes and wrong methods reach Rust, never the Python catch-all."""
    generated = generate_routes(_base_config(), python_operations(_python_app()))
    assert _destination(generated, "GET", "/api/v2/auth/me") == "/api/native_roll.rs"
    assert _destination(generated, "GET", "/api/v1/threads/123") == "/api/index.py"
    assert _destination(generated, "POST", "/api/v1/threads/123") == "/api/native_roll.rs"
    assert _destination(generated, "OPTIONS", "/api/v1/threads/123") == "/api/index.py"
    assert _destination(generated, "GET", "/api/v2/unknown") == "/api/native_roll.rs"


def test_route_generation_is_idempotent_and_anchored() -> None:
    """Running on already-generated ingress does not accumulate stale rules."""
    operations = python_operations(_python_app())
    first = generate_routes(_base_config(), operations)
    second = generate_routes(first, operations)
    assert first == second
    pattern = route_regex("/api/v1/threads/{thread_id}")
    assert re.fullmatch(pattern, "/api/v1/threads/123")
    assert not re.fullmatch(pattern, "/api/v1/threads/123/comments")

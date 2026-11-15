"""The native cutover must not retain shadowed Python handler implementations."""

import json
from collections.abc import Iterator
from pathlib import Path

from fastapi.routing import APIRoute

from app.main import create_app

RETIRED_OPERATIONS = json.loads(
    (Path(__file__).parent / "fixtures" / "retired-python-handlers.json").read_text()
)


def _operations(routes: list[object], prefix: str = "") -> Iterator[tuple[str, str]]:
    """Yield method/path pairs through FastAPI's included-router tree."""
    for route in routes:
        if isinstance(route, APIRoute):
            for method in route.methods or ():
                yield method, prefix + route.path
            continue
        original_router = getattr(route, "original_router", None)
        context = getattr(route, "include_context", None)
        if original_router is not None and context is not None:
            yield from _operations(original_router.routes, prefix + context.prefix)


def test_native_operations_have_no_shadow_python_handlers() -> None:
    """Retire every migrated alias while retaining unrelated Python operations."""
    operations = set(_operations(list(create_app(serve_frontend=False).routes)))
    retired = {
        (method, operation["path"])
        for operation in RETIRED_OPERATIONS
        for method in operation["methods"]
    }
    assert len(retired) == 78
    assert operations.isdisjoint(retired), sorted(operations & retired)
    assert ("POST", "/api/v1/threads/") in operations
    assert ("GET", "/api/v1/sessions/current/") in operations
    assert ("GET", "/api/v2/reading-boundaries/{thread_id}") not in operations

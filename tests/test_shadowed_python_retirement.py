"""The native cutover must not retain shadowed Python handler implementations."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
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


def _retired_operations() -> set[tuple[str, str]]:
    """Return every method/path pair the canonical retirement guard pins."""
    return {
        (method, operation["path"])
        for operation in RETIRED_OPERATIONS
        for method in operation["methods"]
    }


def _assert_no_shadow_python_handlers(operations: set[tuple[str, str]]) -> None:
    """Fail when any supplied operation is still served by a Python handler."""
    retired = _retired_operations()
    assert operations.isdisjoint(retired), sorted(operations & retired)


def test_native_operations_have_no_shadow_python_handlers() -> None:
    """Retire every migrated alias while retaining unrelated Python operations."""
    operations = set(_operations(list(create_app(serve_frontend=False).routes)))
    # 80 historical aliases plus the nine fully retired v1 creator URLs (the
    # two v1 creator URLs with native same-path contracts were already counted)
    # plus ten issue-identity/CBL adoption operations, plus the twenty
    # metrics/taste/reading-plan-sync/session/undo/custom-cbl operations
    # retired on main, plus five thread-issue operations removed here
    # (POST issues, reorder, migrateToIssues, migrateToIssuesSimple,
    # setCurrentIssue). Creators remains on Python.
    assert len(_retired_operations()) == 135
    _assert_no_shadow_python_handlers(operations)
    assert ("GET", "/api/v2/reading-boundaries/{thread_id}") not in operations


def test_guard_rejects_reintroduced_identity_inbox_handler() -> None:
    """All seven identity-inbox operations stay covered by the canonical guard."""
    identity_inbox = {
        (method, operation["path"])
        for operation in RETIRED_OPERATIONS
        if operation["module"] == "app.api.identity_inbox"
        for method in operation["methods"]
    }
    assert len(identity_inbox) == 7
    for operation in identity_inbox:
        with pytest.raises(AssertionError):
            _assert_no_shadow_python_handlers({operation})

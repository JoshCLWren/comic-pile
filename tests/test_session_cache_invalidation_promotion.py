"""Regression coverage for promoting session cache-invalidation out of the router.

Issue #2615 moves the session cache-invalidation helper out of
``app.api.session`` (a router module) and into the cache-invalidation package so
recovery and other non-router callers can invalidate without coupling to router
privates. This module enforces that contract:

- the public helper lives in ``app.cache_invalidation``;
- no production code imports the old private name from a router module;
- the router module no longer defines the private wrapper.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app import cache_invalidation

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_DIRS = [REPOSITORY_ROOT / "app", REPOSITORY_ROOT / "comic_pile"]
ROUTER_MODULE = REPOSITORY_ROOT / "app" / "api" / "session.py"


def test_public_helper_lives_in_cache_invalidation_package() -> None:
    """The promoted helper is a public attribute of the cache package."""
    assert callable(getattr(cache_invalidation, "invalidate_session_caches", None))


def test_router_module_no_longer_defines_private_invalidation_wrapper() -> None:
    """The router must not keep its own private invalidation wrapper."""
    tree = ast.parse(ROUTER_MODULE.read_text(encoding="utf-8"))
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "_invalidate_session_caches" not in defined


def test_no_production_imports_router_private_invalidation_helper() -> None:
    """Production code must not reach into a router for cache invalidation."""
    offenders: list[str] = []
    for directory in PRODUCTION_DIRS:
        for path in sorted(directory.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                module = node.module or ""
                if module in {"app.api.session", "app.services.session_response"}:
                    for alias in node.names:
                        if alias.name == "_invalidate_session_caches":
                            offenders.append(f"{path}: imports {module}.{alias.name}")

    assert not offenders, (
        "Production code still imports the router-private cache-invalidation "
        f"helper: {offenders}"
    )


def test_router_module_does_not_import_session_response_invalidation() -> None:
    """The session router must not pull the old wrapper from session_response."""
    tree = ast.parse(ROUTER_MODULE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module == "app.services.session_response":
            for alias in node.names:
                assert alias.name != "_invalidate_session_caches", (
                    "app.api.session still imports the private invalidation "
                    "helper from app.services.session_response"
                )
#!/usr/bin/env python3
"""Generate Rust-default Vercel ingress from FastAPI's registered OpenAPI surface.

All /api requests default to Rust. Only actual, still-registered Python
operations are routed to api/index.py. Public operations come from the raw
Python OpenAPI document (before pruning/merging the Rust contract); private
routes omitted from OpenAPI are supplemented by registered APIRoute entries.

Run as part of production deployment so removing a Python handler
automatically removes its Vercel exception. --check validates checked-in output.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any, Final

from fastapi import FastAPI
from fastapi.routing import APIRoute

ROOT: Final = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

VERCEL_CONFIG: Final = Path("vercel.json")
PYTHON_DESTINATION: Final = "/api/index.py"
RUST_DESTINATIONS: Final = frozenset({"/api/native_roll.rs", "/api/native_issue.rs"})
API_CATCH_ALL: Final = "/api(?:/.*)?"
HTTP_METHODS: Final = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")
PARAMETER: Final = re.compile(r"\{([^{}]+)\}")


def python_operations(app: FastAPI | None = None) -> list[tuple[str, str]]:
    """Enumerate the complete real FastAPI method/path surface offline.

    The raw OpenAPI contract is authoritative for schema-visible operations.
    Registered APIRoute instances cover hidden routes such as cron and ping.
    Exclude only the synthetic JSON 404 catch-all, not legitimate hidden APIs.
    """
    if app is None:
        # Assemble the actual production router mounts without initializing
        # settings, database pools, or frontend assets. This stays stable
        # across local, CI, and production environments, including pytest's
        # TEST_ENVIRONMENT and development-only debug routes.
        from app.main import _register_lightweight_routers
        from app.router_mounts import build_router_mounts

        app = FastAPI()
        _register_lightweight_routers(app)
        for mount in build_router_mounts("production"):
            if mount.key not in {"debug", "test-helpers"}:
                mount.register(app)
    schema = app.openapi()
    documented = {
        (method.upper(), path)
        for path, paths in schema["paths"].items()
        if path.startswith("/api/")
        for method in paths
        if method.upper() in HTTP_METHODS
    }
    registered: list[tuple[str, str]] = []
    visible: set[tuple[str, str]] = set()
    seen: set[tuple[str, str]] = set()
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/"):
            continue
        if route.path == "/api/{path:path}":
            continue
        for method in sorted(route.methods, key=HTTP_METHODS.index):
            key = (method, route.path)
            if key not in seen:
                registered.append(key)
                seen.add(key)
            if route.include_in_schema:
                visible.add(key)
    # FastAPI's OpenAPI may contain valid operations on routes omitted from
    # APIRoute.include_in_schema through router composition. The raw contract
    # still owns those methods: never silently drop them from Python ingress.
    missing = sorted(visible - documented)
    if missing:
        raise ValueError(
            "Registered schema-visible Python routes missing from raw OpenAPI: "
            f"{missing[:10]}"
        )
    return sorted(set(registered) | documented, key=lambda entry: (entry[1], entry[0]))


def route_regex(path: str) -> str:
    """Convert FastAPI path templates to anchored Vercel-compatible regexes."""
    chunks: list[str] = []
    end = 0
    for match in PARAMETER.finditer(path):
        chunks.append(re.escape(path[end : match.start()]))
        parameter = match.group(1)
        chunks.append(".+" if parameter.endswith(":path") else "[^/]+")
        end = match.end()
    chunks.append(re.escape(path[end:]))
    return "^" + "".join(chunks) + "$"


def native_destination(method: str, path: str, routes: list[dict[str, Any]]) -> str | None:
    """Find the explicit, method-specific Rust ingress selected before fallback."""
    concrete = PARAMETER.sub("1", path)
    for route in routes:
        dest = route.get("dest")
        if dest not in RUST_DESTINATIONS:
            continue
        if route.get("src") == API_CATCH_ALL:
            continue
        methods = route.get("methods")
        if methods and method not in methods:
            continue
        src = route.get("src")
        if isinstance(src, str) and re.fullmatch(src, concrete):
            return str(dest)
    return None


def generate_routes(
    original: dict[str, Any], operations: list[tuple[str, str]]
) -> dict[str, Any]:
    """Produce explicit Python allowlist followed by a default Rust API route.

    The input is the previous Vercel JSON, so native and static rules are
    preserved. All old generated Python rules are replaced, not accumulated.
    """
    routes = original["routes"]
    native = [
        route
        for route in routes
        if route.get("dest") in RUST_DESTINATIONS
        and route.get("src") != API_CATCH_ALL
    ]
    if not native:
        raise ValueError("No native Rust ingress rules; refusing to generate routing")

    python_methods: dict[str, set[str]] = {}
    for method, path in operations:
        if native_destination(method, path, native) is not None:
            continue
        python_methods.setdefault(path, set()).add(method)

    # Preflight to every still-registered Python operation must reach FastAPI's
    # CORS middleware even though OPTIONS is not listed in its OpenAPI schema.
    python_rules = []
    for path, methods in sorted(python_methods.items()):
        methods.add("OPTIONS")
        python_rules.append({
            "src": route_regex(path),
            "methods": [method for method in HTTP_METHODS if method in methods],
            "dest": PYTHON_DESTINATION,
        })

    # Native routes always win. Python exceptions must be checked before Rust
    # catches every remaining /api request, including unknown APIs and 404s.
    remainder = [
        route for route in routes
        if route.get("dest") != PYTHON_DESTINATION
        and not (
            route.get("src") == API_CATCH_ALL
            and route.get("dest") in RUST_DESTINATIONS
        )
        and route not in native
    ]
    # Existing catch-all, even if it previously pointed at Python, is replaced.
    return {
        **original,
        "routes": [
            *native,
            *python_rules,
            {"src": API_CATCH_ALL, "dest": "/api/native_roll.rs"},
            *remainder,
        ],
    }


def render(config: dict[str, Any], operations: list[tuple[str, str]]) -> str:
    """Render the generated Vercel config deterministically."""
    return json.dumps(generate_routes(config, operations), indent=2) + "\n"


def main() -> int:
    """Write fresh routing or fail on stale checked-in output."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vercel", type=Path, default=VERCEL_CONFIG)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    original: dict[str, Any] = json.loads(args.vercel.read_text(encoding="utf-8"))
    expected = render(original, python_operations())
    actual = args.vercel.read_text(encoding="utf-8")
    if args.check:
        if actual != expected:
            print("Vercel Python allowlist is stale: regenerate with "
                  "python scripts/generate_vercel_routes.py")
            return 1
        print("Verified Rust-default Vercel routing and Python allowlist")
        return 0
    args.vercel.write_text(expected, encoding="utf-8")
    print("Generated Rust-default API ingress and Python allowlist")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

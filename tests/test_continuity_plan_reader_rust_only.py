"""Keep the retired v1 continuity-plan reader from silently returning (#4346).

The legacy ``GET /api/v1/continuity-plans/{plan_id}/reader`` was retired in favor
of the native Rust v2 resource ``GET /api/v2/continuity-plans/{plan_id}/reader``
(Rust resource #4797/#4684, Python retirement #4710). These assertions deliberately
do not require an authenticated Rust fixture: they pin the Python route surface,
production ingress, generated contracts, frontend callers and the native route
table so a v1 alias or a dead parallel Rust port fails here instead of silently
reappearing.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from fastapi.routing import APIRoute

from app.main import app

ROOT = Path(__file__).resolve().parents[1]
V1_READER_PATH = "/api/v1/continuity-plans/{plan_id}/reader"
V2_READER_PATH = "/api/v2/continuity-plans/{plan_id}/reader"
V2_READER_SRC = r"^/api/v2/continuity-plans/[0-9]+/reader$"
V1_READER_CONCRETE = "/api/v1/continuity-plans/1/reader"
# Matches a frontend call to the retired v1 reader, but not the still-live
# ``/v1/continuity-plans/${planId}/release-sources/reader`` sibling operation.
V1_READER_CALL = re.compile(r"/v1/continuity-plans/\$\{[^}]+\}/reader(?![\w-])")
RETIRED_MODULES = (
    "app.api.reading_plan_reader",
    "app.services.reading_plan_reader",
    "app.schemas.reading_plan_reader",
)
RETIRED_FILES = tuple(module.replace(".", "/") + ".py" for module in RETIRED_MODULES)

type JsonObject = dict[str, object]


def _as_object(value: object, label: str) -> JsonObject:
    """Narrow one decoded JSON value to an object, failing the test otherwise."""
    assert isinstance(value, dict), f"{label} must be a JSON object"
    return {str(key): item for key, item in value.items()}


def _as_objects(value: object, label: str) -> list[JsonObject]:
    """Narrow one decoded JSON value to an array of objects."""
    assert isinstance(value, list), f"{label} must be a JSON array"
    return [_as_object(item, label) for item in value]


def _load_json(relative: str) -> JsonObject:
    """Load one checked-in JSON document from the repository root."""
    return _as_object(json.loads((ROOT / relative).read_text(encoding="utf-8")), relative)


def _vercel_destination(routes: list[JsonObject], method: str, path: str) -> str | None:
    """Resolve the first matching vercel route destination for one request."""
    for route in routes:
        src = route.get("src")
        if not isinstance(src, str) or re.fullmatch(src, path) is None:
            continue
        methods = route.get("methods")
        if isinstance(methods, list) and method.upper() not in methods:
            continue
        dest = route.get("dest")
        return dest if isinstance(dest, str) else None
    return None


def test_python_exposes_no_v1_plan_reader_handler() -> None:
    """Do not reinstate a Python fallback through any v1 reader alias."""
    matches = [
        route.path
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.path == V1_READER_PATH
        and "GET" in (route.methods or set())
    ]
    assert matches == []
    paths = app.openapi()["paths"]
    assert "get" not in paths.get(V1_READER_PATH, {})


def test_retired_python_reader_modules_stay_deleted() -> None:
    """The exclusive v1 reader modules deleted by #4710 must not return."""
    for module in RETIRED_MODULES:
        assert importlib.util.find_spec(module) is None, module
    for relative in RETIRED_FILES:
        assert not (ROOT / relative).exists(), relative


def test_retirement_is_recorded_in_the_route_inventory() -> None:
    """The inventory records the v1 reader as retired by #4346, replaced by v2."""
    inventory = _load_json("docs/api/v2-route-inventory.json")
    retired = [
        entry
        for entry in _as_objects(
            inventory["retired_legacy_operations"], "retired_legacy_operations"
        )
        if entry["path"] == V1_READER_PATH
    ]
    assert retired == [
        {
            "method": "GET",
            "path": V1_READER_PATH,
            "runtime": "python-fastapi",
            "retired_by_issue": 4346,
            "replacement": f"GET {V2_READER_PATH}",
        }
    ]
    live = [
        entry
        for entry in _as_objects(inventory["operations"], "operations")
        if entry["path"] == V2_READER_PATH
    ]
    assert len(live) == 1
    assert live[0]["method"] == "GET"
    assert live[0]["runtime"] == "native-rust"
    assert live[0]["consumers"] == ["frontend/src/services/api-continuity-plans.ts"]


def test_production_ingress_serves_only_the_v2_plan_reader() -> None:
    """vercel.json routes the v2 reader to native Rust; v1 falls to the catch-all."""
    routes = _as_objects(_load_json("vercel.json")["routes"], "vercel.json routes")
    v2_routes = [route for route in routes if route.get("src") == V2_READER_SRC]
    assert v2_routes == [{"src": V2_READER_SRC, "methods": ["GET"], "dest": "/api/native_roll.rs"}]
    # No operation-specific route may capture the retired v1 reader; the only
    # match is the API catch-all, which lands on the native Rust JSON 404.
    specific = [
        route
        for route in routes
        if route.get("src") not in (None, "/api(?:/.*)?", "/(.*)")
        and re.fullmatch(str(route["src"]), V1_READER_CONCRETE) is not None
    ]
    assert specific == []
    assert _vercel_destination(routes, "GET", V1_READER_CONCRETE) == "/api/native_roll.rs"
    assert _vercel_destination(routes, "GET", "/api/v2/continuity-plans/1/reader") == (
        "/api/native_roll.rs"
    )


def test_route_fragment_declares_no_v1_plan_reader() -> None:
    """The bot-owned route fragment must not resurrect the retired v1 reader."""
    fragment = _load_json("docs/api/route-fragments/continuity-plans.json")
    operations = _as_objects(fragment["operations"], "route fragment operations")
    assert all(operation.get("path") != V1_READER_PATH for operation in operations)


def test_frontend_plan_reader_calls_only_the_v2_rust_route() -> None:
    """Frontend services call only the v2 reader, never the retired v1 path."""
    services = ROOT / "frontend" / "src" / "services"
    for service in sorted(services.glob("*.ts")):
        source = service.read_text(encoding="utf-8")
        assert V1_READER_CALL.search(source) is None, service.relative_to(ROOT).as_posix()
    plan_service = (services / "api-continuity-plans.ts").read_text(encoding="utf-8")
    assert "`/v2/continuity-plans/${planId}/reader`" in plan_service


def test_generated_contracts_have_no_v1_plan_reader_path() -> None:
    """Generated OpenAPI artifacts and the native contract omit the retired path."""
    for relative in (
        "frontend/src/generated/openapi.json",
        "native/contracts/v2-runtime.openapi.json",
        "native/contracts/same-path-runtime.openapi.json",
    ):
        document = _load_json(relative)
        paths = _as_object(document["paths"], f"{relative} paths")
        assert V1_READER_PATH not in paths, relative
    for relative in (
        "frontend/src/generated/openapi.ts",
        "frontend/src/generated/nativeV2Client.ts",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert V1_READER_PATH not in source, relative
        assert V1_READER_CALL.search(source) is None, relative
    runtime = _load_json("native/contracts/v2-runtime.openapi.json")
    assert V2_READER_PATH in _as_object(runtime["paths"], "v2-runtime paths")


def test_native_registers_only_the_v2_plan_reader() -> None:
    """The Rust router exposes the v2 reader and no dead parallel v1 port."""
    lib = (ROOT / "native" / "roll-service" / "src" / "lib.rs").read_text(encoding="utf-8")
    assert (
        '.route(\n            "/api/v2/continuity-plans/{plan_id}/reader",\n            get(reading_plan_reader::read),\n        )'
        in lib
    )
    assert '"/api/v1/continuity-plans/{plan_id}/reader"' not in lib

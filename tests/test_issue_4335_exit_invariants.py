"""Closure-critical invariants for #4335 (Rust cutover exit checklist).

These tests pin code/config facts that the epic exit checklist requires.
They do not prove production deployment or runtime behavior.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_vercel() -> dict:
    return json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))


def test_vercel_builds_only_rust_api_and_static_frontend() -> None:
    """Epic #4335: no Python/Node API runtime in Vercel build config."""
    vercel = _load_vercel()
    builds = vercel.get("builds", [])
    srcs = [b.get("src") for b in builds]
    assert srcs == ["api/native_roll.rs", "package.json"], srcs
    uses = [b.get("use") for b in builds]
    assert "@vercel/rust" in uses
    assert "@vercel/static-build" in uses
    for build in builds:
        src = str(build.get("src", ""))
        use = str(build.get("use", ""))
        assert "python" not in src.lower()
        assert "python" not in use.lower()
        assert src != "api/index.py"


def test_python_api_entrypoint_absent() -> None:
    """Epic #4335: Python FastAPI Vercel entrypoint is removed."""
    assert not (ROOT / "api" / "index.py").exists()
    assert not (ROOT / "app").exists()


def test_vercel_catch_all_routes_to_native_rust() -> None:
    """Epic #4335: API catch-all is served by Rust, not Python."""
    vercel = _load_vercel()
    routes = vercel.get("routes", [])
    catch_alls = [r for r in routes if r.get("src") == "/api(?:/.*)?"]
    assert len(catch_alls) == 1, catch_alls
    assert catch_alls[0].get("dest") == "/api/native_roll.rs"


def test_vercel_routes_do_not_target_python() -> None:
    """Epic #4335: no Vercel route dest points at a Python handler."""
    vercel = _load_vercel()
    for route in vercel.get("routes", []):
        dest = str(route.get("dest", ""))
        assert not dest.endswith(".py"), route
        assert "index.py" not in dest, route

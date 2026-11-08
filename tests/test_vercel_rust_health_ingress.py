"""Guard production Rust liveness and retired Python documentation ingress (#4740).

Local FastAPI endpoints intentionally still exist for developer and transitional
API tests; this validates the deployed Vercel routing and smoke contract.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERCEL = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
WORKFLOW = (ROOT / ".github/workflows/deploy-production.yml").read_text(encoding="utf-8")


def _route_for(path: str, method: str = "GET") -> dict[str, object]:
    """Return the first applicable Vercel route, respecting declaration order."""
    for route in VERCEL["routes"]:
        pattern = route.get("src")
        methods = route.get("methods")
        if pattern and (methods is None or method in methods) and re.fullmatch(
            pattern, path
        ):
            return route
    raise AssertionError(f"No ingress rule matches {method} {path}")


def test_production_health_is_rust_and_never_falls_through_to_python() -> None:
    """Liveness is the existing native v2 route, not FastAPI /health."""
    assert _route_for("/api/v2/health")["dest"] == "/api/native_roll.rs"
    assert _route_for("/api/v2/auth/login", method="POST")["dest"] == (
        "/api/native_roll.rs"
    )


def test_retired_public_docs_and_health_never_start_python_or_serve_spa() -> None:
    """Explicit 404s prevent both the old Python route and SPA fallback."""
    for path in ("/health", "/docs", "/redoc", "/openapi.json"):
        route = _route_for(path)
        assert route["status"] == 404, path
        assert "dest" not in route, path


def test_deploy_smoke_asserts_native_health_and_retains_negative_login() -> None:
    """Both probes verify runtime rather than treating a matching status as proof."""
    health_start = WORKFLOW.index("      - name: Smoke production Rust health")
    login_start = WORKFLOW.index(
        "      - name: Smoke production rejected login on the Rust runtime"
    )
    health_smoke = WORKFLOW[health_start:login_start]
    login_smoke = WORKFLOW[login_start:]
    assert "/api/v2/health" in health_smoke
    assert "/health" not in health_smoke.replace("/api/v2/health", "")
    assert "status" in health_smoke and "200" in health_smoke
    assert "x-comicpile-api-runtime" in health_smoke
    assert '"rust"' in health_smoke
    assert "/api/v2/auth/login" in login_smoke
    assert "401" in login_smoke
    assert "x-comicpile-api-runtime" in login_smoke

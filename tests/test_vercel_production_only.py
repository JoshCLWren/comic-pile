"""Regression coverage for ComicPile's production-only Vercel deployment policy."""

import json
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_vercel_deploys_main_and_disables_non_production_branches() -> None:
    """Only main may receive an automatic Git deployment from Vercel."""
    config = json.loads((REPOSITORY_ROOT / "vercel.json").read_text(encoding="utf-8"))

    assert config["git"]["deploymentEnabled"] == {
        "main": True,
        "*": False,
        "**/*": False,
    }


def test_vercel_gate_covers_slash_containing_factory_branches() -> None:
    """Factory branches must not escape the non-production deployment rule."""
    config = json.loads((REPOSITORY_ROOT / "vercel.json").read_text(encoding="utf-8"))
    deployment_rules = config["git"]["deploymentEnabled"]

    assert deployment_rules["*"] is False
    assert deployment_rules["**/*"] is False
    assert deployment_rules["main"] is True


def test_vercel_keeps_production_static_and_api_routes_intact() -> None:
    """The branch gate must not disturb the production frontend/API split."""
    config = json.loads((REPOSITORY_ROOT / "vercel.json").read_text(encoding="utf-8"))
    routes = config["routes"]

    assert any(route.get("src") == "/api(?:/.*)?" for route in routes)
    assert any(
        route.get("src") == "/" and route.get("dest") == "/index.html"
        for route in routes
    )
    assert any(
        route.get("src") == "/(.*)" and route.get("dest") == "/index.html"
        for route in routes
    )

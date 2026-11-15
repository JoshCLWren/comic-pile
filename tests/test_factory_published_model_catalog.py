"""Catalog-backed free route selection never trusts a manually typed TSV ID."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github/scripts/factory_published_model_catalog.py"
RUNNER = ROOT / ".github/workflows/free-model-factory-run.yml"


@pytest.fixture(scope="module")
def catalog_module():
    spec = importlib.util.spec_from_file_location("factory_published_model_catalog", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def model(model_id: str, prompt: str, completion: str) -> dict:
    return {"id": model_id, "pricing": {"prompt": prompt, "completion": completion}}


def test_openrouter_uses_published_free_ids_and_rejects_paid(catalog_module) -> None:
    catalog = {"data": [
        model("vendor/paid", "0.01", "0.02"),
        model("vendor/free-lying", "0", "0"),
        model("vendor/verified:free", "0", "0"),
        model("vendor/paid:free", "0", "1"),
        {"id": "vendor/unknown:free"},
    ]}
    assert catalog_module.free_model_ids("openrouter-free", catalog) == ["vendor/verified:free"]
    for worker in ("51", "108", "129"):
        assert catalog_module.choose_model("openrouter-free", worker, catalog) == "vendor/verified:free"


def test_vercel_requires_zero_price_on_both_sides(catalog_module) -> None:
    catalog = {"data": [
        {"id": "vendor/zero", "pricing": {"input": "0", "output": 0}},
        {"id": "vendor/unknown", "pricing": {"input": "0"}},
        {"id": "vendor/paid", "pricing": {"input": 0, "output": "0.0001"}},
    ]}
    assert catalog_module.free_model_ids("vercel-ai-gateway", catalog) == ["vendor/zero"]


def test_selection_filters_neon_exclusions_and_is_deterministic(catalog_module) -> None:
    catalog = {"data": [
        model("vendor/a:free", "0", "0"),
        model("vendor/b:free", "0", "0"),
        model("vendor/c:free", "0", "0"),
    ]}
    first = catalog_module.choose_model("openrouter-free", "51", catalog)
    assert first == catalog_module.choose_model("openrouter-free", "51", catalog)
    excluded = {"vendor/a:free", "vendor/b:free"}
    assert catalog_module.choose_model("openrouter-free", "51", catalog, excluded) == "vendor/c:free"
    with pytest.raises(catalog_module.CatalogUnavailable):
        catalog_module.choose_model(
            "openrouter-free", "51", catalog,
            {"vendor/a:free", "vendor/b:free", "vendor/c:free"},
        )


@pytest.mark.parametrize("catalog", [{}, {"data": {}}, {"data": None}])
def test_invalid_catalog_is_not_success(catalog_module, catalog: dict) -> None:
    with pytest.raises(catalog_module.CatalogUnavailable):
        catalog_module.free_model_ids("openrouter-free", catalog)


def test_cli_accepts_fixture_and_preserves_real_published_id(tmp_path: Path) -> None:
    fixture = tmp_path / "upstream.json"
    fixture.write_text(json.dumps({"data": [
        model("example/real:free", "0", "0"),
        model("example/not-free", "1", "0"),
    ]}))
    out = subprocess.run(
        [sys.executable, str(SCRIPT), "--source", "openrouter-free", "--worker", "51",
         "--catalog-json", str(fixture)],
        capture_output=True, text=True, check=True,
    )
    assert json.loads(out.stdout) == {
        "source": "openrouter-free",
        "model": "example/real:free",
        "catalog_verified": True,
    }


def test_workflow_uses_real_catalog_before_open_code_execution() -> None:
    workflow = RUNNER.read_text()
    selection = workflow.split(
        "      - name: Select execution candidate at dispatch time", 1
    )[1].split("      - name: Configure OpenAI-compatible factory provider", 1)[0]
    assert selection.count("factory_published_model_catalog.py") == 2
    assert "runtime_model=vercel/$model" in selection
    assert "runtime_model=openrouter/$model" in selection
    assert '--exclusions-file "$exclusions_file"' in selection
    assert "selected-from-published-zero-price-catalog" in selection
    assert "required cost" not in selection  # No inference-token probes.

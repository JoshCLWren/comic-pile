"""Published discovery must not reject candidates for their price."""

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


def model(model_id: str, prompt: str | None = None, completion: str | None = None) -> dict:
    row = {"id": model_id, "supported_parameters": ["tools"],
           "endpoints": ["/api/v1/chat/completions"]}
    if prompt is not None:
        row["pricing"] = {"prompt": prompt, "completion": completion}
    return row


def test_published_price_does_not_block_candidate(catalog_module) -> None:
    catalog = {"data": [
        model("example/no-price"),
        model("example/paid", "0.01", "0.02"),
        model("example/zero", "0", "0"),
        {**model("example/no-tools"), "supported_parameters": []},
        {**model("example/no-chat"), "endpoints": ["/api/v1/messages"]},
        {"id": "example/metadata-unknown"},
    ]}
    assert catalog_module.catalog_model_ids("openrouter-free", catalog) == [
        "example/metadata-unknown", "example/no-price", "example/paid", "example/zero",
    ]


def test_vercel_filters_modality_not_price(catalog_module) -> None:
    catalog = {"data": [
        {"id": "example/zero", "type": "language", "supported_parameters": ["tools"],
         "pricing": {"input": "0", "output": 0}},
        {"id": "example/paid", "type": "language", "supported_parameters": ["tools"],
         "pricing": {"input": 1, "output": 2}},
        {"id": "example/no-price", "type": "language"},
        {"id": "example/image", "type": "image", "supported_parameters": ["tools"]},
        {"id": "example/no-tools", "type": "language", "supported_parameters": []},
    ]}
    assert catalog_module.catalog_model_ids("vercel-ai-gateway", catalog) == [
        "example/no-price", "example/paid", "example/zero",
    ]


def test_selection_filters_cooldown_and_is_deterministic(catalog_module) -> None:
    catalog = {"data": [model("example/a"), model("example/b"), model("example/c")]}
    first = catalog_module.choose_model("openrouter-free", "51", catalog)
    assert first == catalog_module.choose_model("openrouter-free", "51", catalog)
    assert catalog_module.choose_model("openrouter-free", "51", catalog, {"example/a", "example/b"}) == "example/c"
    with pytest.raises(catalog_module.PublishedCatalogUnavailableError):
        catalog_module.choose_model("openrouter-free", "51", catalog, {"example/a", "example/b", "example/c"})


@pytest.mark.parametrize("catalog", [{}, {"data": {}}, {"data": None}])
def test_invalid_catalog_is_not_success(catalog_module, catalog: dict) -> None:
    with pytest.raises(catalog_module.PublishedCatalogUnavailableError):
        catalog_module.catalog_model_ids("openrouter-free", catalog)


def test_cli_accepts_fixture_with_published_price(tmp_path: Path) -> None:
    fixture = tmp_path / "upstream.json"
    fixture.write_text(json.dumps({"data": [model("example/paid", "4", "2")]}))
    out = subprocess.run(
        [sys.executable, str(SCRIPT), "--source", "openrouter-free", "--worker", "51",
         "--catalog-json", str(fixture)],
        capture_output=True, text=True, check=True,
    )
    assert json.loads(out.stdout) == {
        "source": "openrouter-free", "model": "example/paid",\n        "runtime_model": "openrouter/example/paid", "catalog_listed": True,
    }


def test_execution_workflow_has_no_published_price_gate() -> None:
    workflow = RUNNER.read_text()
    selection = workflow.split("      - name: Select execution candidate at dispatch time", 1)[1]
    assert selection.count("factory_published_model_catalog.py") == 2
    assert "runtime_model=vercel/$model" in selection
    assert "runtime_model=openrouter/$model" in selection
    assert "selected-from-published-catalog" in selection
    assert "Require Vercel model to remain zero-price" not in workflow


def test_prior_retirement_is_not_permanent_ban(tmp_path: Path) -> None:
    fixture = tmp_path / "provider.json"
    fixture.write_text(json.dumps({"data": [model("example/previously-failed")]}))
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--source", "openrouter-free",
         "--worker", "128", "--catalog-json", str(fixture)],
        text=True, capture_output=True, check=True,
    )
    assert json.loads(result.stdout)["model"] == "example/previously-failed"

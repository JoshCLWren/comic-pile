"""Provider discovery is driven by live catalogs and integration metadata."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).resolve().parents[1] / ".github/scripts/factory_provider_candidates.py"
sys.path.insert(0, str(SCRIPT.parent))


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("factory_provider_candidates", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CANDIDATES = load_module()


def test_all_compatible_registry_providers_have_catalog_adapters() -> None:
    from factory_provider_registry import PROVIDERS

    for source in PROVIDERS:
        catalog = json.dumps({"data": [{"id": "example/new-upstream-model"}]})
        result = CANDIDATES.discover(source, catalog)
        assert result.status == "available", source
        assert [item.model for item in result.candidates] == ["example/new-upstream-model"]


def test_price_and_free_suffix_do_not_control_discovery() -> None:
    catalog = json.dumps({"data": [
        {"id": "example/paid", "pricing": {"prompt": "4", "completion": "1"}},
        {"id": "example/unpriced"},
        {"id": "example/no-tools", "supported_parameters": []},
        {"id": "example/image", "type": "image"},
        {"id": "example/free", "pricing": {"prompt": "0", "completion": "0"}},
    ]})
    result = CANDIDATES.discover("openrouter-free", catalog)
    assert [item.model for item in result.candidates] == [
        "example/free", "example/paid", "example/unpriced",
    ]
    assert all(item.runtime_model.startswith("openrouter/") for item in result.candidates)


def test_opencode_uses_live_selector_as_published() -> None:
    result = CANDIDATES.discover(
        "opencode-free",
        "opencode/code-1\nopencode/paid-2\nother/model\n",
    )
    assert result.status == "available"
    assert [item.model for item in result.candidates] == ["code-1", "paid-2"]


def test_omniroute_requires_provider_published_routes() -> None:
    assert CANDIDATES.discover("omniroute-free", json.dumps({"data": []})).candidates == ()
    result = CANDIDATES.discover(
        "omniroute-free",
        json.dumps({"data": [{"id": "example/dynamic-route"}]}),
    )
    assert [item.runtime_model for item in result.candidates] == [
        "omniroute/example/dynamic-route",
    ]


def test_invalid_catalog_fails_without_inventing_models() -> None:
    result = CANDIDATES.discover("openrouter-free", "not json")
    assert result.status == "invalid"
    assert result.candidates == ()


def test_kilo_without_catalog_is_runtime_only() -> None:
    result = CANDIDATES.discover("kilo-auto", "ignored")
    assert result.mode == "runtime_only"
    assert result.status == "indeterminate"
    assert result.candidates == ()


def test_unknown_provider_fails() -> None:
    try:
        CANDIDATES.discover("nonexistent", "{}")
    except ValueError as exc:
        assert "unsupported factory provider" in str(exc)
    else:
        raise AssertionError("unknown provider was silently allowed")

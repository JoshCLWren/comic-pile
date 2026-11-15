"""Behavioral tests for the single source of truth for OpenCode provider IDs."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REGISTRY_PATH = Path(".github/scripts/factory_provider_registry.py")


@pytest.fixture(scope="module")
def registry():
    spec = importlib.util.spec_from_file_location("factory_provider_registry", REGISTRY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_every_compatible_provider_round_trips_published_model_id(registry):
    """Selector is canonical provider plus unmodified upstream model ID."""
    for source, provider in registry.PROVIDERS.items():
        model = "upstream/model-v1"
        env = {provider.credential: "secret", **dict.fromkeys(provider.additional_credentials, "account")}
        resolution = registry.resolve(source, model, env)
        assert resolution["runtime_model"] == f"{provider.provider}/{model}"
        assert resolution["configured"]
        assert resolution["branch_suffix"] == source
        if provider.needs_registration(model):
            config = registry.compatible_config(source, model, env)["providers"][provider.provider]
            assert config["models"][model]["modelID"] == model
            assert "secret" not in str(config)
            assert config["env"] == [provider.credential]
        else:
            with pytest.raises(ValueError):
                registry.compatible_config(source, model, env)


def test_nvidia_published_vendor_prefix_survives(registry):
    env = {"NVIDIA_API_KEY": "secret"}
    model = "nvidia/nemotron-3.5-bolt-e4b"
    assert registry.resolve("nvidia", model, env)["runtime_model"] == "nvidia/nvidia/nemotron-3.5-bolt-e4b"
    assert registry.compatible_config("nvidia", model, env)["providers"]["nvidia"]["models"][model]["modelID"] == model
    assert not registry.resolve("nvidia", "openai/gpt-oss-20b", env)["configure_adapter"]


def test_missing_credentials_and_unknown_sources_fail_closed(registry):
    assert registry.resolve("groq-free", "openai/gpt-oss-120b", {})["reason"] == "missing-GROQ_API_KEY"
    with pytest.raises(ValueError):
        registry.compatible_config("groq-free", "openai/gpt-oss-120b", {})
    assert not registry.resolve("cloudflare-workers-ai", "@cf/openai/gpt-oss-20b", {"CLOUDFLARE_API_TOKEN": "secret"})["configured"]
    with pytest.raises(ValueError):
        registry.resolve("fake-provider", "model", {})
    for bad_model in ("", "bad\nmodel", "/missing-model"):
        with pytest.raises(ValueError):
            registry.resolve("groq-free", bad_model, {})


def test_roster_provider_sources_are_registered(registry):
    """Every fixed-model provider-backed worker must have an executable spec."""
    rows = Path(".github/free-model-factories.tsv").read_text().splitlines()
    native_sources = {"opencode-free", "openrouter-free", "kilo-auto", "omniroute-free"}
    for row in rows:
        if not row or row.startswith("#"):
            continue
        worker, source, model, *_ = row.split("\t")
        if source not in native_sources:
            spec = registry.get_spec(source, model)
            assert registry.resolve(source, model, {})["runtime_model"] == f"{spec.provider}/{model}", worker


def test_workflow_consumes_registry_instead_of_reimplementing_it():
    runner = Path(".github/workflows/free-model-factory-run.yml").read_text()
    assert "factory_provider_registry.py resolve" in runner
    assert "factory_provider_registry.py config" in runner
    assert "provider_id=" not in runner
    assert "base_url='https://" not in runner

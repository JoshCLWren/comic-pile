"""Exercise the provider registry's outputs, not shell-script string literals."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / ".github/scripts/factory_provider_registry.py"
RUNNER = ROOT / ".github/workflows/free-model-factory-run.yml"
ROSTER = ROOT / ".github/free-model-factories.tsv"


@pytest.fixture(scope="module")
def registry():
    sys.path.insert(0, str(REGISTRY.parent))
    return importlib.import_module("factory_provider_registry")


def rows() -> list[tuple[str, str]]:
    return [
        (part[1], part[2])
        for line in ROSTER.read_text().splitlines()
        if line and not line.startswith("#") and (part := line.split("\t"))
    ]


def test_compatible_sources_have_provider_records(registry) -> None:
    excluded = {"opencode-free", "openrouter-free", "kilo-auto", "omniroute-free"}
    assert {source for source, _ in rows()} - excluded <= registry.PROVIDERS.keys()


@pytest.mark.parametrize(
    ("source", "expected", "model"),
    [
        ("gemini-free", "google", "gemini-3.8-flash"),
        ("groq-free", "groq", "openai/gpt-oss-120b"),
        ("vercel-ai-gateway", "vercel", "nvidia/nemotron-3.5-lightning-free"),
        ("cohere-eval", "cohere", "command-a-plus-05-2026"),
        ("nvidia", "nvidia", "nvidia/nemotron-3.5-bolt-e4b"),
        ("aion-free", "aion", "aion-labs/aion-3.5-mini"),
        ("typhoon-free", "typhoon", "typhoon-v2.5-30b-a3b-instruct"),
        ("cloudflare-workers-ai", "cloudflare-workers-ai", "@cf/openai/gpt-oss-20b"),
    ],
)
def test_exact_upstream_model_survives_selector_and_config(
    registry, source: str, expected: str, model: str,
) -> None:
    spec = registry.PROVIDERS[source]
    env = {spec.credential: "test-token"}
    if spec.account_env:
        env[spec.account_env] = "test-account"
    selected = registry.resolve(source, model, env)
    assert selected["configured"] is True
    assert selected["runtime_model"] == f"{expected}/{model}"
    config = registry.config(source, model, env)
    entry = config["providers"][expected]
    assert entry["models"][model]["modelID"] == model
    assert entry["env"] == [spec.credential]
    assert "test-token" not in json.dumps(config)


def test_all_roster_models_use_the_same_runtime_mapping(registry) -> None:
    env = {spec.credential: "test-token" for spec in registry.PROVIDERS.values()}
    env["CLOUDFLARE_ACCOUNT_ID"] = "test-account"
    for source, model in rows():
        if source not in registry.PROVIDERS:
            continue
        selected = registry.resolve(source, model, env)
        assert selected["configured"] is True
        assert selected["runtime_model"] == f"{selected['provider_id']}/{model}"


def test_nvidia_registration_uses_model_not_worker_id(registry) -> None:
    ids = {model for source, model in rows() if source == "nvidia"}
    assert registry.NVIDIA_UNCATALOGUED <= ids
    for model in ids:
        decision = registry.resolve("nvidia", model, {"NVIDIA_API_KEY": "test-token"})
        assert decision["requires_registration"] == (model in registry.NVIDIA_UNCATALOGUED)


def test_missing_credentials_do_not_create_provider_config(registry) -> None:
    for source, model in rows():
        if source not in registry.PROVIDERS:
            continue
        result = registry.resolve(source, model, {})
        assert result["configured"] is False
        assert result["reason"].startswith("missing-")
        with pytest.raises(ValueError, match="missing-"):
            registry.config(source, model, {})


@pytest.mark.parametrize("bad", ["", "/model", "vendor//model", "../model", "bad\nmodel"])
def test_invalid_model_id_is_rejected(registry, bad: str) -> None:
    with pytest.raises(ValueError, match="Invalid published model ID"):
        registry.resolve("groq-free", bad, {"GROQ_API_KEY": "test-token"})


def test_cli_config_matches_cli_model_selector() -> None:
    env = {**os.environ, "GROQ_API_KEY": "test-token"}
    argv = ["--source", "groq-free", "--model", "openai/gpt-oss-120b"]
    results = []
    for cmd in ("resolve", "config"):
        completed = subprocess.run(
            [sys.executable, str(REGISTRY), cmd, *argv],
            capture_output=True, check=True, text=True, env=env,
        )
        results.append(json.loads(completed.stdout))
        assert "test-token" not in completed.stdout
    selected, configured = results
    assert selected["runtime_model"] == "groq/openai/gpt-oss-120b"
    assert configured["providers"]["groq"]["models"][selected["model_id"]]["modelID"] == selected["model_id"]


def test_workflow_uses_registry_in_both_runtime_steps() -> None:
    workflow = RUNNER.read_text()
    assert "factory_provider_registry.py resolve" in workflow
    assert "factory_provider_registry.py config" in workflow
    assert "provider_registration=$provider_registration" in workflow
    assert "steps.lane.outputs.provider_registration == 'true'" in workflow
    assert "provider_id='google'" not in workflow
    assert "provider_id='groq'" not in workflow
    assert "steps.lane.outputs.worker == '130'" not in workflow

"""Factory roster source keys map to canonical, published OpenCode selectors."""

from pathlib import Path


def test_new_fleet_uses_published_opencode_provider_selectors() -> None:
    """Quota source IDs must not become invented provider IDs in OpenCode."""
    runner = Path(".github/workflows/free-model-factory-run.yml").read_text()
    for source, provider in {
        "gemini-free": "google",
        "groq-free": "groq",
        "aion-free": "aion",
        "cohere-eval": "cohere",
        "typhoon-free": "typhoon",
    }.items():
        assert f"{source}) provider_id='{provider}' ;;" in runner
        assert f"provider_id='{provider}'" in runner
    assert 'runtime_model="vercel/${model}"' in runner
    assert 'runtime_model="nvidia/${model}"' in runner
    assert "base_url='https://integrate.api.nvidia.com/v1'" in runner
    assert "(steps.lane.outputs.worker == '130' || steps.lane.outputs.worker == '131')" in runner
    assert 'models: {($model): {name: $model, modelID: $model}}' in runner
    assert 'headers: (if $provider == "google"' in runner
    assert 'runtime_model="vercel-ai-gateway/${model}"' not in runner


def test_nvidia_vendor_prefix_does_not_get_stripped() -> None:
    """The full published NVIDIA API ID follows the OpenCode provider prefix."""
    runner = Path(".github/workflows/free-model-factory-run.yml").read_text()
    assert 'if [[ "$model" == nvidia/* ]]' in runner
    assert '[[ "$model" != nvidia/nvidia/* ]]' in runner
    assert 'runtime_model="nvidia/${model}"' in runner

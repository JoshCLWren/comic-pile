"""Regression tests for OpenCode/OpenRouter free-only lane pin guards."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

VALIDATE_PATH = Path('.github/scripts/validate-free-model-factories.py')


def _load_validate_module():
    """Import the roster validator module without requiring package layout."""
    spec = importlib.util.spec_from_file_location(
        'validate_free_model_factories',
        VALIDATE_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def validate():
    """Load the free-model factory validator helpers."""
    return _load_validate_module()


def test_opencode_free_pins_accept_free_roster_ids(validate) -> None:
    """OpenCode free lanes accept big-pickle, *-free, and muse-spark ids."""
    assert validate.opencode_model_is_free('big-pickle')
    assert validate.opencode_model_is_free('mimo-v2.5-free')
    assert validate.opencode_model_is_free('mimo-v2.6-flash-free')
    assert validate.opencode_model_is_free('muse-spark-1.2-contributor-free')
    assert not validate.opencode_model_is_free('paid-frontier')
    assert not validate.opencode_model_is_free('openrouter/foo:free')


def test_openrouter_free_pins_require_free_tier_ids(validate) -> None:
    """OpenRouter free lanes accept :free ids, openrouter/free, or $0 promo ids."""
    assert validate.openrouter_model_is_free('cohere/north-mini-code:free')
    assert validate.openrouter_model_is_free('openrouter/free')
    assert validate.openrouter_model_is_free('stealth/union-alpha')
    assert validate.openrouter_model_is_free('qwen/qwen3.8-27b:free')
    assert not validate.openrouter_model_is_free('stealth/ox-alpha')
    assert not validate.openrouter_model_is_free('openai/gpt-4o')
    assert not validate.openrouter_model_is_free('xiaomi/mimo-v2.6-flash')


def test_manifest_openrouter_pins_are_all_free(validate) -> None:
    """Fail closed if any openrouter-free TSV pin leaves the free tier."""
    rows = []
    with Path('.github/free-model-factories.tsv').open(
        encoding='utf-8',
        newline='',
    ) as handle:
        for line in handle:
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            worker, source, model, *_rest = line.rstrip('\n').split('\t')
            rows.append({'worker': worker, 'source': source, 'model': model})
    openrouter = [row for row in rows if row['source'] == 'openrouter-free']
    assert openrouter
    for row in openrouter:
        assert validate.openrouter_model_is_free(row['model']), row
    opencode = [row for row in rows if row['source'] == 'opencode-free']
    assert opencode
    for row in opencode:
        assert validate.opencode_model_is_free(row['model']), row
    z_ai = [row for row in rows if row['source'] == 'z-ai']
    assert z_ai
    for row in z_ai:
        assert validate.z_ai_model_is_free(row['model']), row
    ollama = [row for row in rows if row['source'] == 'ollama-cloud']
    assert ollama
    for row in ollama:
        assert validate.ollama_cloud_model_is_free(row['model']), row
    vercel = [row for row in rows if row['source'] == 'vercel-ai-gateway']
    assert vercel == []
    assert all(row['worker'] != '72' for row in rows)
    assert 'stealth/pixel-canary' not in {row['model'] for row in rows}
    mistral = [row for row in rows if row['source'] == 'mistral']
    assert len(mistral) == 1
    assert mistral[0]['worker'] == '48'
    assert mistral[0]['model'] == 'codestral-latest'
    assert validate.mistral_model_is_pinned(mistral[0]['model'])


def test_z_ai_and_ollama_cloud_pin_guards_reject_paid_ids(validate) -> None:
    """Paid GLMs and unpublished Ollama Cloud ids cannot occupy these lanes."""
    assert validate.z_ai_model_is_free('glm-4.5-flash')
    assert validate.z_ai_model_is_free('z-ai/glm-4.5-flash')
    assert validate.z_ai_model_is_free('glm-4.7-flash')
    assert validate.z_ai_model_is_free('z-ai/glm-4.7-flash')
    assert not validate.z_ai_model_is_free('glm-4.7')
    assert not validate.z_ai_model_is_free('glm-5')
    assert not validate.z_ai_model_is_free('glm-4.6')
    assert validate.ollama_cloud_model_is_free('nemotron-3-nano:30b')
    assert validate.ollama_cloud_model_is_free('gpt-oss:20b')
    assert not validate.ollama_cloud_model_is_free('llama3')


def test_mistral_pin_is_codestral_latest_not_mistral_small(validate) -> None:
    """Native Mistral lanes accept only codestral-latest."""
    assert validate.mistral_model_is_pinned('codestral-latest')
    assert validate.mistral_model_is_pinned('mistral/codestral-latest')
    assert not validate.mistral_model_is_pinned('mistral-small')
    assert not validate.mistral_model_is_pinned('mistral/mistral-small')
    assert not validate.mistral_model_is_pinned('mistral-small-latest')
    assert not validate.mistral_model_is_pinned('codestral-2501')

def test_opencode_zen_promo_union_alpha_is_free(validate) -> None:
    """Bare Zen union-alpha is a time-boxed $0 promo free pin."""
    assert validate.opencode_model_is_free("union-alpha")
    assert not validate.opencode_model_is_free("stealth/union-alpha")


def test_opencode_longcat_lane_pins_gateway_id_not_analytics_slug(validate) -> None:
    """LongCat lane pins the Zen gateway id, not OpenCode's analytics slug.

    OpenCode's public data surface uses ``longcat-2.5-preview`` as a usage
    slug, but the Zen gateway, models.dev, and the OpenCode Zen docs all
    publish ``longcat-2.5-preview-free`` as the callable model id. The
    analytics slug must not be whitelisted as free, otherwise a
    non-existent id passes the fail-closed opencode-free guard and the lane
    fails at OpenCode smoke on every run.
    """
    assert validate.opencode_model_is_free("longcat-2.5-preview-free")
    assert not validate.opencode_model_is_free("longcat-2.5-preview")

    manifest = Path(".github/free-model-factories.tsv")
    pinned: list[str] = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split("\t")
        if fields[1] == "opencode-free":
            pinned.append(fields[2])
    assert "longcat-2.5-preview-free" in pinned
    assert "longcat-2.5-preview" not in pinned


def test_new_slots_pin_apodex_and_native_ling_31(validate) -> None:
    """Workers 74 and 75 are the hand-grown Apodex and native Ling slots."""
    rows = validate.load_roster_rows(validate.MANIFEST)
    by_worker = {row["worker"]: row for row in rows}
    assert by_worker["46"]["model"] == "kilo-auto/free"
    assert by_worker["74"]["source"] == "openrouter-free"
    assert by_worker["74"]["model"] == "apodex/apodex-1.1-mini:free"
    assert validate.openrouter_model_is_free(by_worker["74"]["model"])
    assert by_worker["75"]["source"] == "opencode-free"
    assert by_worker["75"]["model"] == "ling-3.1-flash-free"
    assert by_worker["75"]["model"] != "inclusionai/ling-3.1-flash"
    assert validate.opencode_model_is_free(by_worker["75"]["model"])
    assert "deepseek-v4-flash-free" not in {row["model"] for row in rows}
    assert "z-ai/glm-5.2:free" not in {row["model"] for row in rows}


def test_worker_76_fledge_alpha_free_is_retired_by_discovery(validate) -> None:
    """Worker 76 was retired once fledge-alpha-free left the Zen catalog."""
    rows = validate.load_roster_rows(validate.MANIFEST)
    by_worker = {row["worker"]: row for row in rows}
    assert by_worker["46"]["source"] == "kilo-auto"
    assert by_worker["46"]["model"] == "kilo-auto/free"
    assert by_worker["74"]["model"] == "apodex/apodex-1.1-mini:free"
    assert by_worker["75"]["model"] == "ling-3.1-flash-free"
    assert by_worker["75"]["model"] != "inclusionai/ling-3.1-flash"
    assert "76" not in by_worker
    assert "fledge-alpha-free" not in {row["model"] for row in rows}
    assert "inclusionai/ling-3.1-flash" not in {row["model"] for row in rows}

def test_new_slots_pin_nvidia_kimi_k3_and_glm_53(validate) -> None:
    """Workers 77–78 are Harvy-smoked native NVIDIA NIM slots (kimi-k3, glm-5.3)."""
    rows = validate.load_roster_rows(validate.MANIFEST)
    by_worker = {row["worker"]: row for row in rows}
    assert by_worker["46"]["model"] == "kilo-auto/free"
    assert by_worker["77"]["source"] == "nvidia"
    assert by_worker["77"]["model"] == "moonshotai/kimi-k3"
    assert by_worker["77"]["minute"] == "35"
    assert by_worker["78"]["source"] == "nvidia"
    assert by_worker["78"]["model"] == "z-ai/glm-5.3"
    assert by_worker["78"]["minute"] == "0"


def test_workers_79_to_82_pin_oct_11_smoked_free_models(validate) -> None:
    """Workers 79-82 are Oct 11 OpenCode smokes that returned model text (PONG)."""
    rows = validate.load_roster_rows(validate.MANIFEST)
    by_worker = {row["worker"]: row for row in rows}
    assert by_worker["46"]["source"] == "kilo-auto"
    assert by_worker["46"]["model"] == "kilo-auto/free"
    assert by_worker["79"]["source"] == "opencode-free"
    assert by_worker["79"]["model"] == "step-5-preview-free"
    assert by_worker["79"]["minute"] == "30"
    assert validate.opencode_model_is_free(by_worker["79"]["model"])
    assert by_worker["80"]["source"] == "nvidia"
    assert by_worker["80"]["model"] == "z-ai/glm-5.3-flash"
    assert by_worker["80"]["minute"] == "40"
    assert by_worker["81"]["source"] == "nvidia"
    assert by_worker["81"]["model"] == "deepseek-ai/deepseek-v4.1-flash"
    assert by_worker["81"]["minute"] == "50"
    assert by_worker["82"]["source"] == "z-ai"
    assert by_worker["82"]["model"] == "glm-4.7-flash"
    assert by_worker["82"]["minute"] == "55"
    assert validate.z_ai_model_is_free(by_worker["82"]["model"])
    # big-pickle is never grown as a first pin when the roster has none.
    assert "big-pickle" not in {row["model"] for row in rows}
    assert not any(
        row["source"] == "openrouter-free" and row["worker"] in {"79", "80", "81", "82"}
        for row in rows
    )


def test_workers_83_to_86_pin_nvidia_nemotron_and_muse_glimmer(validate) -> None:
    """Workers 83-86 are debian OpenCode NVIDIA smokes; worker 59 is retired."""
    rows = validate.load_roster_rows(validate.MANIFEST)
    by_worker = {row["worker"]: row for row in rows}
    assert by_worker["46"]["source"] == "kilo-auto"
    assert by_worker["46"]["model"] == "kilo-auto/free"
    assert by_worker["48"]["source"] == "mistral"
    assert by_worker["48"]["model"] == "codestral-latest"
    assert by_worker["55"]["source"] == "ollama-cloud"
    assert by_worker["55"]["model"] == "nemotron-3-nano:30b"
    assert "59" not in by_worker
    assert "ling-3.0-flash-fin-free" not in {row["model"] for row in rows}
    assert by_worker["75"]["model"] == "ling-3.1-flash-free"
    assert by_worker["83"]["source"] == "opencode-free"
    assert by_worker["83"]["model"] == "cat-jam-free"
    assert by_worker["83"]["minute"] == "45"
    assert "84" not in by_worker
    assert "85" not in by_worker
    assert by_worker["86"]["source"] == "nvidia"
    assert by_worker["86"]["model"] == "meta/muse-glimmer-30b"
    assert by_worker["86"]["minute"] == "15"
    assert by_worker["80"]["source"] == "nvidia"
    assert by_worker["81"]["source"] == "nvidia"

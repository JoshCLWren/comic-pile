"""Regression tests for OpenCode/OpenRouter free-only lane pin guards."""

from __future__ import annotations

import importlib.util
import json
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
    """LongCat's callable id is the gateway ``*-free`` form, now lock-retired.

    OpenCode's public data surface uses ``longcat-2.5-preview`` as a usage
    slug, but the Zen gateway, models.dev, and the OpenCode Zen docs all
    publish ``longcat-2.5-preview-free`` as the callable model id. The
    analytics slug must not be whitelisted as free, otherwise a
    non-existent id passes the fail-closed opencode-free guard. Worker 73
    retired when that gateway id left the free catalog; the analytics slug
    still must not be pinned.
    """
    assert validate.opencode_model_is_free("longcat-2.5-preview-free")
    assert not validate.opencode_model_is_free("longcat-2.5-preview")

    manifest = Path(".github/free-model-factories.tsv")
    lock = json.loads(Path(".github/factory-expected-workers.json").read_text())
    pinned: list[str] = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split("\t")
        if fields[1] == "opencode-free":
            pinned.append(fields[2])
    assert "longcat-2.5-preview-free" not in pinned
    assert "longcat-2.5-preview" not in pinned
    assert 73 in lock["retired_workers"]
    assert "longcat-2.5-preview-free" in lock["retired_models"]


def test_discovered_free_models_reuse_existing_worker_slots(validate) -> None:
    """Free promos replace retired Apodex/Ling without adding worker IDs."""
    rows = validate.load_roster_rows(validate.MANIFEST)
    by_worker = {row["worker"]: row for row in rows}
    lock = json.loads(Path(".github/factory-expected-workers.json").read_text())
    assert by_worker["46"]["model"] == "kilo-auto/free"
    for retired in ("apodex/apodex-1.1-mini:free", "ling-3.1-flash-free"):
        assert retired in lock["retired_models"]
    for worker, model in (
        ("74", "deepseek-v4.1-flash-free"),
        ("75", "nemotron-3.5-super-vl-free"),
    ):
        pin = by_worker.get(worker)
        if pin is not None and pin["model"] == model:
            assert pin["source"] == "opencode-free"
            assert validate.opencode_model_is_free(pin["model"])
            assert pin["scheduler"] == "dispatcher"
        else:
            # These promotional models may be retired by discovery later.
            assert model in lock["retired_models"]



def test_worker_56_dots_preview_is_retired_by_discovery(validate) -> None:
    """A dead OpenRouter preview pin cannot reenter the generated roster."""
    rows = validate.load_roster_rows(validate.MANIFEST)
    lock = json.loads(Path(".github/factory-expected-workers.json").read_text())
    assert "56" not in {row["worker"] for row in rows}
    assert 56 in lock["retired_workers"]
    assert 56 not in lock["expected_workers"]
    assert "dots-studio/dots-3-note-preview:free" in lock["retired_models"]


def test_worker_76_fledge_alpha_free_is_retired_by_discovery(validate) -> None:
    """The historical Fledge Alpha retirement remains locked."""
    rows = validate.load_roster_rows(validate.MANIFEST)
    by_worker = {row["worker"]: row for row in rows}
    lock = json.loads(Path(".github/factory-expected-workers.json").read_text())
    assert by_worker["46"]["model"] == "kilo-auto/free"
    assert "76" not in by_worker
    assert 76 in lock["retired_workers"]
    assert "fledge-alpha-free" in lock["retired_models"]
    assert "fledge-alpha-free" not in {row["model"] for row in rows}
    assert "inclusionai/ling-3.1-flash" not in {row["model"] for row in rows}


def test_discovered_nvidia_410_retires_kimi_and_glm_workers(validate) -> None:
    """NVIDIA 410 discovery retires worker 77 and the later-dead GLM 5.3 pin."""
    rows = validate.load_roster_rows(validate.MANIFEST)
    lock = json.loads(Path(".github/factory-expected-workers.json").read_text())
    by_worker = {row["worker"]: row for row in rows}
    assert "77" not in by_worker
    assert 77 in lock["retired_workers"]
    assert "moonshotai/kimi-k3" in lock["retired_models"]
    assert "78" not in by_worker
    assert 78 in lock["retired_workers"]
    assert 78 not in lock["expected_workers"]
    assert "z-ai/glm-5.3" in lock["retired_models"]


def test_workers_79_to_82_pin_oct_11_smoked_free_models(validate) -> None:
    """Workers 79 and 81 retired with discovery; workers 80 and 82 keep their Oct 11 pins."""
    rows = validate.load_roster_rows(validate.MANIFEST)
    by_worker = {row["worker"]: row for row in rows}
    lock = json.loads(Path(".github/factory-expected-workers.json").read_text())
    assert by_worker["46"]["source"] == "kilo-auto"
    assert by_worker["46"]["model"] == "kilo-auto/free"
    assert "79" not in by_worker
    assert 79 in lock["retired_workers"]
    assert "step-5-preview-free" in lock["retired_models"]
    assert "step-5-preview-free" not in {row["model"] for row in rows}
    assert by_worker["80"]["source"] == "nvidia"
    assert by_worker["80"]["model"] == "z-ai/glm-5.3-flash"
    assert by_worker["80"]["minute"] == "40"
    assert "81" not in by_worker
    assert 81 in lock["retired_workers"]
    assert "deepseek-ai/deepseek-v4.1-flash" in lock["retired_models"]
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
    """Worker 83 Cat Jam is retired; worker 86 Muse Glimmer and 59 stay as-is."""
    rows = validate.load_roster_rows(validate.MANIFEST)
    by_worker = {row["worker"]: row for row in rows}
    lock = json.loads(Path(".github/factory-expected-workers.json").read_text())
    assert by_worker["46"]["source"] == "kilo-auto"
    assert by_worker["46"]["model"] == "kilo-auto/free"
    assert by_worker["48"]["source"] == "mistral"
    assert by_worker["48"]["model"] == "codestral-latest"
    assert by_worker["55"]["source"] == "ollama-cloud"
    assert by_worker["55"]["model"] == "nemotron-3-nano:30b"
    assert "59" not in by_worker
    assert "ling-3.0-flash-fin-free" not in {row["model"] for row in rows}
    assert "83" not in by_worker
    assert 83 in lock["retired_workers"]
    assert "cat-jam-free" in lock["retired_models"]
    assert "84" not in by_worker
    assert "85" not in by_worker
    assert by_worker["86"]["source"] == "nvidia"
    assert by_worker["86"]["model"] == "meta/muse-glimmer-30b"
    assert by_worker["86"]["minute"] == "0"
    assert by_worker["80"]["source"] == "nvidia"
    assert "81" not in by_worker



def test_workers_68_and_69_openrouter_laguna_are_retired(validate) -> None:
    """OpenRouter Laguna :free pins retire before free access ends 2026-10-31."""
    rows = validate.load_roster_rows(validate.MANIFEST)
    by_worker = {row["worker"]: row for row in rows}
    lock = json.loads(Path(".github/factory-expected-workers.json").read_text())
    assert "68" not in by_worker
    assert "69" not in by_worker
    assert 68 in lock["retired_workers"]
    assert 69 in lock["retired_workers"]
    assert "poolside/laguna-s-2.1:free" in lock["retired_models"]
    assert "poolside/laguna-xs-2.1:free" in lock["retired_models"]
    assert by_worker["11"]["source"] == "nvidia"
    assert by_worker["11"]["model"] == "poolside/laguna-xs-2.1"
    assert by_worker["46"]["source"] == "kilo-auto"
    assert by_worker["46"]["model"] == "kilo-auto/free"


def test_workers_94_95_retired_after_catalog_discovery(validate) -> None:
    """Both MiniMax 94 and NVIDIA Super VL 95 remain retired after discovery."""
    rows = validate.load_roster_rows(validate.MANIFEST)
    by_worker = {row["worker"]: row for row in rows}
    lock = json.loads(Path(".github/factory-expected-workers.json").read_text())
    assert by_worker["46"]["source"] == "kilo-auto"
    assert by_worker["46"]["model"] == "kilo-auto/free"
    assert "94" not in by_worker
    assert 94 in lock["retired_workers"]
    assert "minimax/minimax-m3.1-flash:free" in lock["retired_models"]
    assert "95" not in by_worker
    assert 95 in lock["retired_workers"]
    assert 95 not in lock["expected_workers"]
    assert "nvidia/nemotron-3.5-super-vl-120b-a12b" in lock["retired_models"]
    # The OpenRouter :free Super VL id was not smoked (daily free cap), so it is not pinned.
    assert "nvidia/nemotron-3.5-super-vl:free" not in {row["model"] for row in rows}


def test_ghost_workers_49_58_63_73_83_94_are_retired(validate) -> None:
    """Six ghost free-catalog lanes retire; kilo-auto 46 and OpenCode 42 stay."""
    rows = validate.load_roster_rows(validate.MANIFEST)
    by_worker = {row["worker"]: row for row in rows}
    lock = json.loads(Path(".github/factory-expected-workers.json").read_text())
    for worker in (49, 58, 63, 73, 83, 94):
        assert str(worker) not in by_worker
        assert worker in lock["retired_workers"]
        assert worker not in lock["expected_workers"]
    assert "space-bunny-free" in lock["retired_models"]
    assert "muse-spark-1.3-contributor-free" in lock["retired_models"]
    assert "nvidia/nemotron-3-super-120b-a12b:free" in lock["retired_models"]
    assert "longcat-2.5-preview-free" in lock["retired_models"]
    assert "cat-jam-free" in lock["retired_models"]
    assert "minimax/minimax-m3.1-flash:free" in lock["retired_models"]
    assert by_worker["42"]["source"] == "opencode-free"
    assert by_worker["42"]["model"] == "nemotron-3-ultra-free"
    assert by_worker["46"]["source"] == "kilo-auto"
    assert by_worker["46"]["model"] == "kilo-auto/free"

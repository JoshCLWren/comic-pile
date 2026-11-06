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


def _load_snapshot_pins() -> dict[str, dict[str, str]]:
    """Load pins from the automation-owned snapshot."""
    snapshot_path = Path(".github/factory-roster-snapshot.json")
    data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    return {pin["worker"]: pin for pin in data.get("pins", [])}


def _assert_committed_pin(
    by_worker: dict[str, dict[str, str]],
    lock: dict[str, list],
    worker: str,
    *,
    source: str | None = None,
    model: str | None = None,
    minute: str | None = None,
) -> dict[str, str] | None:
    """Assert a live pin's identity, or a consistently-recorded retirement.

    Discovery rewrites ``.github/factory-roster-snapshot.json`` and
    ``factory-expected-workers.json`` in the same commit that retires a
    catalog-absent fixed-provider pin. This guard accepts exactly that
    transition so a legitimate retirement PR is green on its own head (#3802),
    while a silent re-pin or an inconsistent lock still fails.

    The assertion is now snapshot-driven: the automation-owned
    ``factory-roster-snapshot.json`` is the source of truth for active pins,
    and the lock records retirements. Hard-coded model/source arguments are
    retained for documentation but overridden by the snapshot when present.

    Returns:
        The live roster row, or ``None`` when discovery retired the worker.
    """
    snapshot_pins = _load_snapshot_pins()
    snap = snapshot_pins.get(worker)
    row = by_worker.get(worker)

    # Determine expected values: snapshot overrides explicit args
    expected_source = snap["source"] if snap else source
    expected_model = snap["model"] if snap else model

    if row is None:
        # Worker absent from live TSV → must be retired
        assert expected_source in {'nvidia', 'openrouter-free', None}, (worker, expected_source)
        assert int(worker) not in lock['expected_workers'], worker
        assert int(worker) in lock['retired_workers'], worker
        # If we have an expected model from snapshot, it should be in retired_models
        if expected_model:
            assert expected_model in lock['retired_models'], (worker, expected_model)
        # If caller supplied a legacy model, also verify it
        if model and model != expected_model:
            assert model in lock['retired_models'], (worker, model)
        return None

    # Worker present → must match snapshot (and optional explicit checks)
    if expected_source:
        assert row['source'] == expected_source, (worker, row['source'], expected_source)
    else:
        assert row['source'] == source, (worker, row['source'])
    if expected_model:
        assert row['model'] == expected_model, (worker, row['model'], expected_model)
    elif model:
        assert row['model'] == model, (worker, row['model'])
    if minute is not None:
        assert row['minute'] == minute, (worker, row['minute'])
    # Also ensure snapshot agrees if it exists
    if snap:
        assert row['source'] == snap['source'], (worker, row['source'], snap['source'])
        assert row['model'] == snap['model'], (worker, row['model'], snap['model'])
    return row


def test_protected_source_disappearance_fails_committed_pin(validate) -> None:
    """A protected-source pin that vanishes must not be accepted as a retirement.

    Discovery only retires catalog-absent ``nvidia``/``openrouter-free`` pins.
    A protected source (here ``z-ai``) disappearing must fail the guard rather
    than being silently treated as a legitimate retirement (#3802 review).
    """
    rows = validate.load_roster_rows(validate.MANIFEST)
    lock = json.loads(Path(".github/factory-expected-workers.json").read_text())
    by_worker = {row["worker"]: row for row in rows}
    by_worker.pop("82", None)
    with pytest.raises(AssertionError):
        _assert_committed_pin(by_worker, lock, "82", source="z-ai", model="glm-4.7-flash")


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
    assert validate.openrouter_model_is_free('stealth/crouton-alpha')
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
    assert not ollama  # Worker 55 retired after quota exhaustion.
    vercel = [row for row in rows if row['source'] == 'vercel-ai-gateway']
    assert vercel == []
    assert all(row['worker'] != '72' for row in rows)
    assert 'stealth/pixel-canary' not in {row['model'] for row in rows}
    mistral = [row for row in rows if row['source'] == 'mistral']
    assert not mistral  # Worker 48 retired after quota exhaustion.
    lock = json.loads(Path('.github/factory-expected-workers.json').read_text())
    assert {48, 55}.issubset(set(lock['retired_workers']))
    assert {'codestral-latest', 'nemotron-3-nano:30b'}.issubset(set(lock['retired_models']))


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
    _assert_committed_pin(by_worker, lock, "78", source="nvidia", model="z-ai/glm-5.3")


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
    _assert_committed_pin(by_worker, lock, "80", source="nvidia", model="z-ai/glm-5.3-flash")
    assert "81" not in by_worker
    assert 81 in lock["retired_workers"]
    assert "deepseek-ai/deepseek-v4.1-flash" in lock["retired_models"]
    z_ai_pin = _assert_committed_pin(
        by_worker, lock, "82", source="z-ai", model="glm-4.7-flash"
    )
    if z_ai_pin is not None:
        assert validate.z_ai_model_is_free(z_ai_pin["model"])
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
    assert {"48", "55"}.isdisjoint(by_worker)
    assert {48, 55}.issubset(set(lock["retired_workers"]))
    assert "59" not in by_worker
    assert "ling-3.0-flash-fin-free" not in {row["model"] for row in rows}
    assert "83" not in by_worker
    assert 83 in lock["retired_workers"]
    assert "cat-jam-free" in lock["retired_models"]
    assert "84" not in by_worker
    assert "85" not in by_worker
    _assert_committed_pin(
        by_worker, lock, "86", source="nvidia", model="meta/muse-glimmer-30b"
    )
    _assert_committed_pin(
        by_worker, lock, "80", source="nvidia", model="z-ai/glm-5.3-flash"
    )
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
    _assert_committed_pin(
        by_worker, lock, "11", source="nvidia", model="poolside/laguna-xs-2.1"
    )
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
    _assert_committed_pin(
        by_worker,
        lock,
        "95",
        source="nvidia",
        model="nvidia/nemotron-3.5-super-vl-120b-a12b",
    )
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

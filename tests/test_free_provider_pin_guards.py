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
    source: str,
    model: str,
    minute: str | None = None,
) -> dict[str, str] | None:
    """Accept a recorded catalog retirement, never an unexplained disappearance.

    For live workers, the automation-owned snapshot is authoritative so
    catalog-driven pin changes do not require hand-editing these assertions.
    Retired workers must still have an allowed original source and a durable
    worker/model retirement entry in the lock (#3802).
    """
    snapshot_pin = _load_snapshot_pins().get(worker)
    row = by_worker.get(worker)
    if row is None:
        assert source in {'nvidia', 'openrouter-free'}, (worker, source)
        assert int(worker) not in lock['expected_workers'], worker
        assert int(worker) in lock['retired_workers'], worker
        assert model in lock['retired_models'], (worker, model)
        return None

    expected_source = snapshot_pin['source'] if snapshot_pin else source
    expected_model = snapshot_pin['model'] if snapshot_pin else model
    assert row['source'] == expected_source, (worker, row['source'], expected_source)
    assert row['model'] == expected_model, (worker, row['model'], expected_model)
    if minute is not None:
        assert row['minute'] == minute, (worker, row['minute'])
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
    protected = next(row for row in rows if row["source"] == "z-ai")
    by_worker.pop(protected["worker"])
    with pytest.raises(AssertionError):
        _assert_committed_pin(
            by_worker, lock, protected["worker"],
            source=protected["source"], model=protected["model"],
        )


def test_committed_guard_rejects_unexpected_live_model_drift(validate) -> None:
    """A live worker silently repinned without refreshing the snapshot fails."""
    rows = validate.load_roster_rows(validate.MANIFEST)
    pin = next(row for row in rows if row['source'] == 'nvidia')
    by_worker = {row['worker']: row for row in rows}
    by_worker[pin['worker']] = {**pin, 'model': 'unapproved-model'}
    lock = json.loads(Path('.github/factory-expected-workers.json').read_text())
    with pytest.raises(AssertionError):
        _assert_committed_pin(
            by_worker,
            lock,
            pin['worker'],
            source=pin['source'],
            model=pin['model'],
        )


def test_roster_snapshot_guard_detects_stale_pins(validate, tmp_path: Path) -> None:
    """A stale or altered snapshot cannot pass the pre-commit roster validator."""
    rows = validate.load_roster_rows(validate.MANIFEST)
    lock_path = Path('.github/factory-expected-workers.json')
    snapshot_path = Path('.github/factory-roster-snapshot.json')
    validate.assert_roster_snapshot_matches(
        rows, lock_path=lock_path, snapshot_path=snapshot_path
    )

    snapshot = json.loads(snapshot_path.read_text(encoding='utf-8'))
    snapshot['pins'][0]['model'] = 'unexpected-model'
    stale_path = tmp_path / 'stale-snapshot.json'
    stale_path.write_text(json.dumps(snapshot), encoding='utf-8')
    with pytest.raises(AssertionError, match='snapshot is stale'):
        validate.assert_roster_snapshot_matches(
            rows, lock_path=lock_path, snapshot_path=stale_path
        )


def test_roster_snapshot_guard_detects_stale_lock(validate, tmp_path: Path) -> None:
    """An altered expected-worker lock cannot be excused by the snapshot."""
    rows = validate.load_roster_rows(validate.MANIFEST)
    lock = json.loads(Path('.github/factory-expected-workers.json').read_text())
    lock['expected_workers'].remove(int(rows[0]['worker']))
    stale_lock_path = tmp_path / 'stale-lock.json'
    stale_lock_path.write_text(json.dumps(lock), encoding='utf-8')
    with pytest.raises(AssertionError, match='expected-worker lock'):
        validate.assert_roster_snapshot_matches(
            rows,
            lock_path=stale_lock_path,
            snapshot_path=Path('.github/factory-roster-snapshot.json'),
        )


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
    assert 'stealth/pixel-canary' not in {row['model'] for row in rows}
    mistral = [row for row in rows if row['source'] == 'mistral']
    assert not mistral  # Worker 48 retired after quota exhaustion.
    lock = json.loads(Path('.github/factory-expected-workers.json').read_text())
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


def test_free_catalog_retirements_do_not_require_original_worker_ids(validate) -> None:
    """Free-model rotation may change worker IDs without weakening paid-model guards."""
    rows = validate.load_roster_rows(validate.MANIFEST)
    lock = json.loads(Path(".github/factory-expected-workers.json").read_text())
    by_worker = {row["worker"]: row for row in rows}
    active = {int(worker) for worker in by_worker}
    retired = set(lock["retired_workers"])
    assert active == set(lock["expected_workers"])
    assert active.isdisjoint(retired)
    assert all(
        row["model"] not in lock["retired_models"]
        for row in rows
        if row["source"] in {"opencode-free", "openrouter-free"}
    )
    assert all(
        row["model"] == "kilo-auto/free"
        for row in rows if row["source"] == "kilo-auto"
    )


def test_retired_catalog_models_are_not_silently_reenrolled(validate) -> None:
    """A historically retired model needs explicit unretirement, not a reused ID."""
    rows = validate.load_roster_rows(validate.MANIFEST)
    lock = json.loads(Path(".github/factory-expected-workers.json").read_text())
    retired_models = set(lock["retired_models"])
    assert not retired_models.intersection(
        row["model"] for row in rows
        if row["source"] in {"opencode-free", "openrouter-free"}
    )
    assert not any(
        row["source"] == "openrouter-free"
        and not validate.openrouter_model_is_free(row["model"])
        for row in rows
    )

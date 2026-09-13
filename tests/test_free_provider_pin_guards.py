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
    assert validate.opencode_model_is_free('muse-spark-1.2-contributor-free')
    assert not validate.opencode_model_is_free('paid-frontier')
    assert not validate.opencode_model_is_free('openrouter/foo:free')


def test_openrouter_free_pins_require_free_tier_ids(validate) -> None:
    """OpenRouter free lanes accept only :free ids or openrouter/free."""
    assert validate.openrouter_model_is_free('cohere/north-mini-code:free')
    assert validate.openrouter_model_is_free('openrouter/free')
    assert not validate.openrouter_model_is_free('stealth/ox-alpha')
    assert not validate.openrouter_model_is_free('openai/gpt-4o')


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

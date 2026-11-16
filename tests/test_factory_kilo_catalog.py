"""Kilo model choices come from the CLI, not pinned source files."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".github/scripts"))
KILO = importlib.import_module("factory_kilo_catalog")


def test_cli_models_are_discovered_without_allowed_id_list() -> None:
    catalog = "kilo-auto/synthetic-model-a\nkilo-auto/synthetic-model-b\nother/non-kilo-model\n"
    assert KILO.discover_models(catalog) == ["kilo-auto/synthetic-model-a", "kilo-auto/synthetic-model-b"]


def test_selection_respects_cooldowns_but_not_price_or_roster() -> None:
    catalog = "kilo-auto/synthetic-model-a\nkilo-auto/synthetic-model-b\nother/non-kilo-model\n"
    selected = KILO.choose(catalog, "123", {"kilo-auto/synthetic-model-a"})
    assert selected["runtime_model"] == "kilo-auto/synthetic-model-b"
    with pytest.raises(ValueError):
        KILO.choose(catalog, "123", {"kilo-auto/synthetic-model-a", "kilo-auto/synthetic-model-b"})

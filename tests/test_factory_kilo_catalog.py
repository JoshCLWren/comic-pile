"""Kilo model choices come from the CLI, not pinned source files."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".github/scripts"))
KILO = importlib.import_module("factory_kilo_catalog")


def test_cli_models_are_discovered_without_allowed_id_list() -> None:
    catalog = "kilocode/synthetic-model-a\nother/synthetic-model-b\n"
    assert KILO.discover_models(catalog) == ["kilocode/synthetic-model-a", "other/synthetic-model-b"]


def test_selection_respects_cooldowns_but_not_price_or_roster() -> None:
    catalog = "kilocode/synthetic-model-a\nother/synthetic-model-b\n"
    selected = KILO.choose(catalog, "123", {"kilocode/synthetic-model-a"})
    assert selected["runtime_model"] == "other/synthetic-model-b"
    with pytest.raises(ValueError):
        KILO.choose(catalog, "123", {"kilocode/synthetic-model-a", "other/synthetic-model-b"})

"""Confirm legacy Reading Order compatibility stays outside Step 27 batch authority."""

from __future__ import annotations

from scripts.reader_order_migration import ALL_MANIFESTS, CONFIRMATION
from scripts.legacy_reading_order_step23b_migration import CONFIRMATION as STEP23_CONFIRMATION


def test_step27_batch_does_not_replace_legacy_reading_order_import_path() -> None:
    """One-shot batch migrates Dependency debris; Reading Orders stay on Step 23B."""
    assert CONFIRMATION == "STEP27-READER-ORDER"
    assert STEP23_CONFIRMATION != CONFIRMATION
    assert ALL_MANIFESTS
    assert "from-reading-order" not in ALL_MANIFESTS
    assert all("reading-order" not in manifest for manifest in ALL_MANIFESTS)

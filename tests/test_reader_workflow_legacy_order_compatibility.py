"""Confirm Step 23B legacy Reading Orders participate in the Step 27 batch."""

from __future__ import annotations

from scripts.reader_order_migration import ALL_MANIFESTS, CONFIRMATION
from scripts.legacy_reading_order_step23b_migration import CONFIRMATION as STEP23_CONFIRMATION
from app.services.reader_order_migration_coordinator import LEGACY_READING_ORDERS_MANIFEST


def test_step27_batch_includes_legacy_reading_order_manifest() -> None:
    """One-shot batch reports/receipts Step 23B as already-migrated/safe/blocked."""
    assert CONFIRMATION == "STEP27-READER-ORDER"
    assert STEP23_CONFIRMATION == "STEP23B-LEGACY-READING-ORDERS"
    assert CONFIRMATION != STEP23_CONFIRMATION
    assert LEGACY_READING_ORDERS_MANIFEST in ALL_MANIFESTS
    assert LEGACY_READING_ORDERS_MANIFEST == "legacy-reading-orders"
    # The HTTP import helper remains a separate product surface; the batch owns status.
    assert "from-reading-order" not in ALL_MANIFESTS

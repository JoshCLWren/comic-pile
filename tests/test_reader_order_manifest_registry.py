"""Coverage for the complete Step 27 production manifest registry."""

from __future__ import annotations

from collections import Counter

from app.services.explicit_reader_order_migration import (
    PRODUCTION_EXPLICIT_READER_ORDER_SPECS,
    _explicit_classifications,
    _load_step14_index,
)
from app.services.source_backed_reader_order_migration import (
    PRODUCTION_SOURCE_BACKED_SPECS,
)


def test_production_manifests_cover_every_step14_reader_order_family() -> None:
    """Every explicitly classified reader-order family has one generic manifest."""
    index = _load_step14_index()
    _, families = _explicit_classifications(index)
    classified = {
        family_key
        for family_key, rows in families.items()
        if any(row["classification"] == "reading_plan_order" for row in rows)
    }
    registered = Counter(
        family_key
        for spec in (
            *PRODUCTION_EXPLICIT_READER_ORDER_SPECS.values(),
            *PRODUCTION_SOURCE_BACKED_SPECS.values(),
        )
        for family_key in spec.classification_family_keys
    )

    assert set(registered) == classified
    assert all(count == 1 for count in registered.values())


def test_production_source_manifests_cover_every_step14_cbl_source() -> None:
    """All high-confidence Step 14A source hashes are enumerable by the batch CLI."""
    index = _load_step14_index()
    source_hash_map = index["lookup"]["14A"]["source_hash_map"]
    assert isinstance(source_hash_map, dict)

    registered_hashes = {
        spec.expected_content_hash for spec in PRODUCTION_SOURCE_BACKED_SPECS.values()
    }
    assert set(source_hash_map) <= registered_hashes
    assert registered_hashes - set(source_hash_map) == {
        "bb54dfc094a2a7c469b6baa77f6751a8d30ea034ede24d686ba1ab4a968ae0ca"
    }

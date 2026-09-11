"""Offline integrity checks for persisted Step 14D production evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/recovery/step14d-noted-semantic-families-evidence.json"
ALLOWED = {"reading_plan_order", "standalone_prerequisite", "needs_review"}
EXPECTED_TOTALS = {
    "reading_plan_order": 114,
    "standalone_prerequisite": 39,
    "needs_review": 1,
}


def _sha256(ids: list[int]) -> str:
    """Fingerprint an ordered dependency-ID manifest."""
    return hashlib.sha256(",".join(str(value) for value in ids).encode()).hexdigest()


def _report() -> dict[str, object]:
    """Load the persisted Step 14D evidence."""
    return cast(dict[str, object], json.loads(EVIDENCE.read_text(encoding="utf-8")))


def test_step14d_population_and_classifications_reconcile() -> None:
    """Every dependency appears once in exactly one allowed classification."""
    report = _report()
    scope = cast(dict[str, object], report["scope"])
    families = cast(list[dict[str, object]], report["families"])
    totals = cast(dict[str, int], report["classification_totals"])

    seen: set[int] = set()
    actual: dict[str, int] = dict.fromkeys(EXPECTED_TOTALS, 0)
    for family in families:
        classification = str(family["classification"])
        ids = cast(list[int], family["dependency_ids"])
        assert classification in ALLOWED
        assert family["sha256"] == _sha256(ids)
        assert not seen.intersection(ids)
        seen.update(ids)
        actual[classification] += len(ids)

    scope_ids = cast(list[int], scope["dependency_ids"])
    assert len(scope_ids) == len(set(scope_ids)) == scope["count"] == 154
    assert scope["manifest_sha256"] == _sha256(scope_ids)
    assert seen == set(scope_ids)
    assert totals == EXPECTED_TOTALS
    assert actual == EXPECTED_TOTALS


def test_step14d_prior_slice_overlap_is_zero() -> None:
    """The noted-only remainder has no overlap with completed Steps 14A-14C."""
    report = _report()
    scope = cast(dict[str, object], report["scope"])
    prior = cast(dict[str, object], report["prior_exclusions"])
    assert scope["overlap_step14a"] == 0
    assert scope["overlap_step14b"] == 0
    assert scope["overlap_step14c"] == 0
    assert len(cast(list[int], prior["step14c_dependency_ids"])) == 77
    assert scope["distinct_note_count"] == 152


def test_step14d_mixed_projects_keep_semantic_splits() -> None:
    """Fourth World, X-Men, and Ultimate are not flattened for convenience."""
    report = _report()
    mixed = {
        str(row["project"]): row
        for row in cast(list[dict[str, object]], report["mixed_families"])
    }
    assert set(mixed) == {
        "Fourth World / Mister Miracle",
        "Late-90s X-Men",
        "Ultimate Universe",
    }
    assert mixed["Fourth World / Mister Miracle"]["standalone_prerequisite"] == [
        1383,
        1784,
    ]
    assert mixed["Late-90s X-Men"]["standalone_prerequisite"] == [
        1577,
        1578,
        1579,
        1580,
        1581,
        1848,
        1849,
        1850,
        1851,
        1852,
    ]
    ultimate = mixed["Ultimate Universe"]
    assert ultimate["needs_review"] == [1929]
    assert set(cast(list[int], ultimate["standalone_prerequisite"])) >= {
        1582,
        1912,
        1913,
        1916,
        1918,
        1928,
        1936,
        1937,
    }


def test_step14d_blocking_and_linked_rules_are_annotations() -> None:
    """Live blocking and linked-rule coverage reconcile without driving semantics."""
    report = _report()
    blocking = cast(dict[str, object], report["current_blocking_overlay"])
    linked = cast(dict[str, object], report["linked_continuity_rules"])

    blocking_ids = cast(list[int], blocking["dependency_ids"])
    assert blocking["count"] == len(blocking_ids) == 50
    assert blocking["sha256"] == _sha256(blocking_ids)
    assert blocking["by_classification"] == {
        "reading_plan_order": 34,
        "standalone_prerequisite": 15,
        "needs_review": 1,
    }
    assert 1929 in blocking_ids

    assert linked["dependency_count"] == 154
    assert linked["linked_rule_count"] == 154
    assert linked["distinct_linked_rule_count"] == 154
    assert linked["missing_rule_count"] == 0
    assert linked["exact_endpoint_item_read_mirror_count"] == 154
    assert linked["nontrivial_payload_count"] == 0
    assert "did not determine" in str(linked["interpretation"])


def test_step14d_group_context_has_no_sequence_order_authority() -> None:
    """Dependency groups remain evidence/provenance in this slice."""
    clustering = cast(dict[str, object], _report()["dependency_group_clustering"])
    assert len(cast(list[list[object]], clustering["clusters"])) == 22
    assert clustering["ordered_membership_overlap_count"] == 0
    assert clustering["ungrouped_dependency_ids"] == [1866, 1895, 1898, 1924, 1929]


def test_step14d_needs_review_fails_closed_with_resolution_evidence() -> None:
    """The sole unresolved row records why it is unsafe and what would resolve it."""
    review = cast(dict[str, object], _report()["needs_review"])
    assert review["dependency_ids"] == [1929]
    assert "conflicts with publisher chronology" in str(review["reason"])
    assert len(cast(list[str], review["evidence_needed"])) == 2
    assert len(cast(list[str], review["sources"])) == 2


def test_step14d_safety_stops_before_step14e() -> None:
    """The artifact authorizes no mutation and does not begin Step 14E."""
    report = _report()
    safety = cast(dict[str, object], report["safety"])
    assert report["result"] == "PASS"
    assert safety["production_mutated"] is False
    assert safety["dependencies_modified"] is False
    assert safety["reading_plans_modified"] is False
    assert safety["legacy_reading_orders_modified"] is False
    assert safety["continuity_rules_modified"] is False
    assert safety["blocked_state_modified"] is False
    assert safety["sequence_order_modified"] is False
    assert safety["roll_behavior_modified"] is False
    assert safety["migration_authorized"] is False
    assert safety["architecture_hold_2363_lifted"] is False
    assert safety["step_14e_started"] is False

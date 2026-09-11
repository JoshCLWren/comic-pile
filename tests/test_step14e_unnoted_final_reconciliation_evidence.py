"""Offline integrity tests for Step 14E and the final Step 14 reconciliation."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/recovery/step14e-unnoted-final-reconciliation-evidence.json"
FINAL_INDEX = ROOT / "docs/recovery/step14-final-classification-index.json"
ALLOWED = {"reading_plan_order", "standalone_prerequisite", "needs_review"}


def _load(path: Path) -> dict[str, Any]:
    """Load one persisted Step 14 artifact."""
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _sha256(ids: list[int]) -> str:
    """Fingerprint an ordered dependency-ID manifest."""
    return hashlib.sha256(",".join(str(value) for value in ids).encode()).hexdigest()


def test_step14e_population_and_classifications_reconcile() -> None:
    """Every Step 14E dependency is classified exactly once."""
    report = _load(EVIDENCE)
    scope = cast(dict[str, Any], report["scope"])
    families = cast(list[dict[str, Any]], report["families"])
    expected = {"reading_plan_order": 97, "standalone_prerequisite": 51, "needs_review": 1}

    seen: set[int] = set()
    actual: Counter[str] = Counter()
    for family in families:
        classification = str(family["classification"])
        ids = cast(list[int], family["ids"])
        assert classification in ALLOWED
        assert family["count"] == len(ids)
        assert family["sha256"] == _sha256(ids)
        assert not seen.intersection(ids)
        seen.update(ids)
        actual[classification] += len(ids)

    scope_ids = cast(list[int], scope["dependency_ids"])
    assert len(scope_ids) == len(set(scope_ids)) == scope["count"] == 149
    assert scope["note_null_total"] == 153
    assert scope["excluded_prior_ids"] == [18, 19, 20, 21]
    assert scope["manifest_sha256"] == _sha256(scope_ids)
    assert scope["postgres_md5"] == "faf0757e63f533d08786d0558138b83b"
    assert seen == set(scope_ids)
    assert dict(actual) == expected
    assert report["classification_totals"] == expected


def test_step14e_linked_rules_and_groups_are_annotations() -> None:
    """Rule/group coverage reconciles without becoming classification authority."""
    report = _load(EVIDENCE)
    linked = cast(dict[str, Any], report["linked_continuity_rules"])
    groups = cast(dict[str, Any], report["dependency_group_clustering"])

    assert linked["dependency_count"] == 149
    assert linked["linked_rule_count"] == 149
    assert linked["distinct_linked_rule_count"] == 149
    assert linked["missing_rule_count"] == 0
    assert linked["exact_endpoint_item_read_mirror_count"] == 149
    assert linked["rule_note_nonnull_dependency_ids"] == [1329, 1330, 1331]
    assert "did not determine" in str(linked["interpretation"])

    assert groups["dependencies_touching_at_least_one_group"] == 149
    assert groups["distinct_groups_touched"] == 27
    assert groups["ordered_membership_overlap_count"] == 0


def test_step14e_keeps_mixed_semantics_split() -> None:
    """Known mixed projects remain split instead of being flattened."""
    families = {
        str(row["key"]): row
        for row in cast(list[dict[str, Any]], _load(EVIDENCE)["families"])
    }
    assert families["ultimate_reusable_standalone_rules"]["ids"] == [1321, 1329, 1429, 1430]
    assert families["ultimate_universe_reader_order"]["classification"] == "reading_plan_order"
    assert families["xmen_children_of_atom_story_handoff"]["classification"] == "standalone_prerequisite"
    assert families["xmen_magneto_rex_story_handoff"]["classification"] == "standalone_prerequisite"
    assert families["xmen_chronology_reader_order"]["classification"] == "reading_plan_order"


def test_step14e_needs_review_fails_closed() -> None:
    """The new unresolved row records the contradictory evidence explicitly."""
    review = cast(dict[str, Any], _load(EVIDENCE)["needs_review"])
    assert review["dependency_ids"] == [101]
    row = cast(dict[str, Any], review["rows"][0])
    assert row["dependency_id"] == 101
    assert "conflicts with publisher Rotworld chronology" in row["reason"]
    assert len(cast(list[str], row["evidence_needed"])) == 2
    assert len(cast(list[str], row["sources"])) == 2


def test_final_step14_union_and_global_totals_reconcile() -> None:
    """All five slices cover production once and totals sum exactly."""
    final = cast(dict[str, Any], _load(EVIDENCE)["final_reconciliation"])
    assert final["production_total"] == 103313
    assert final["slice_counts"] == {"14A": 101632, "14B": 1301, "14C": 77, "14D": 154, "14E": 149}
    assert sum(cast(dict[str, int], final["slice_counts"]).values()) == 103313
    assert final["slice_union_count"] == 103313
    assert final["duplicate_dependency_ids_across_slices"] == 0
    assert final["missing_dependency_ids"] == 0
    assert final["unexplained_dependency_ids"] == 0
    assert final["exactly_one_slice_match_min"] == 1
    assert final["exactly_one_slice_match_max"] == 1

    totals = cast(dict[str, int], final["global_classification_totals"])
    assert totals == {"reading_plan_order": 103217, "standalone_prerequisite": 94, "needs_review": 2}
    assert sum(totals.values()) == 103313


def test_final_step14_unresolved_list_is_explicit() -> None:
    """Both remaining ambiguities are visible in the final package."""
    final = cast(dict[str, Any], _load(EVIDENCE)["final_reconciliation"])
    unresolved = cast(list[dict[str, Any]], final["remaining_needs_review"])
    assert [row["dependency_id"] for row in unresolved] == [101, 1929]
    assert unresolved[0]["slice"] == "14E"
    assert unresolved[1]["slice"] == "14D"


def test_final_legacy_order_and_bprd_invariants_hold() -> None:
    """Legacy orders remain classified and B.P.R.D. remains dependency-free."""
    final = cast(dict[str, Any], _load(EVIDENCE)["final_reconciliation"])
    legacy = cast(dict[str, Any], final["legacy_reading_orders"])
    assert legacy["overlap_dependency_count"] == 13
    assert legacy["overlap_dependency_ids"] == [18,19,20,21,1806,1807,1808,1810,1811,1832,1833,1846,1847]
    assert legacy["classified_slice"] == "14C"
    assert legacy["migration_performed"] is False

    bprd = cast(dict[str, Any], final["bprd_invariant"])
    assert bprd["canonical_plan_name"] == "B.P.R.D."
    assert bprd["surviving_dependency_overlap_count"] == 0
    assert bprd["dependency_ids"] == []
    assert bprd["modified"] is False


def test_final_blocking_overlay_is_annotation_only() -> None:
    """The global blocker surface reconciles without altering classifications."""
    report = _load(EVIDENCE)
    step14e = cast(dict[str, Any], report["current_blocking_overlay"])
    assert step14e["count"] == 70
    assert step14e["by_classification"] == {"reading_plan_order": 31, "standalone_prerequisite": 39, "needs_review": 0}

    final = cast(dict[str, Any], report["final_reconciliation"])
    global_overlay = cast(dict[str, Any], final["global_current_blocking_overlay"])
    assert global_overlay == {"reading_plan_order": 2575, "standalone_prerequisite": 54, "needs_review": 1, "total": 2630, "active_needs_review_ids": [1929]}


def test_final_index_covers_large_selectors_and_exact_small_slices() -> None:
    """The thin index resolves every slice without a 103k-row duplicate ledger."""
    index = _load(FINAL_INDEX)
    lookup = cast(dict[str, Any], index["lookup"])

    assert re.fullmatch(lookup["14A"]["note_regex"], "cbl-order:source:abc:1->2")
    assert lookup["14A"]["count"] == 101632
    assert len(cast(dict[str, list[object]], lookup["14A"]["source_hash_map"])) == 11
    assert lookup["14B_group16"]["count"] == 1228
    assert lookup["14B_temporary_ultimate"]["count"] == 73

    slices = cast(dict[str, dict[str, Any]], lookup["explicit_slices"])
    seen: set[int] = set()
    by_slice: Counter[str] = Counter()
    for slice_name, slice_data in slices.items():
        for family in cast(list[dict[str, Any]], slice_data["families"]):
            ids = cast(list[int], family["ids"])
            assert not seen.intersection(ids)
            seen.update(ids)
            by_slice[slice_name] += len(ids)

    assert by_slice == Counter({"14D": 154, "14E": 149, "14C": 77})
    assert len(seen) == 380
    assert 101632 + 1301 + len(seen) == index["production_dependency_total"]
    assert index["remaining_needs_review_ids"] == [101, 1929]


def test_step14_completion_does_not_authorize_migration() -> None:
    """Step 14 completion preserves the architecture hold and mutation boundary."""
    report = _load(EVIDENCE)
    safety = cast(dict[str, Any], report["safety"])
    assert report["result"] == "PASS"
    assert safety == {
        "production_mutated": False,
        "dependencies_modified": False,
        "reading_plans_modified": False,
        "legacy_reading_orders_modified": False,
        "continuity_rules_modified": False,
        "blocked_state_modified": False,
        "sequence_order_modified": False,
        "roll_behavior_modified": False,
        "migration_authorized": False,
        "architecture_hold_2363_lifted": False,
        "downstream_migration_started": False,
    }

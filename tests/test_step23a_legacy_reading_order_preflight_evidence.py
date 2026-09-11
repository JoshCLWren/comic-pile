"""Offline integrity checks for the Step 23A legacy Reading Order preflight."""

from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/recovery/step23a-legacy-reading-order-preflight-evidence.json"
SUMMARY = ROOT / "docs/recovery/step23a-legacy-reading-order-preflight.md"
STEP14_INDEX = ROOT / "docs/recovery/step14-final-classification-index.json"
STEP14C = ROOT / "docs/recovery/step14c-reader-order-family-evidence.json"
SCRIPT = ROOT / "scripts/audit_step23a_legacy_reading_order_preflight.py"
EXPECTED_OVERLAP = [18, 19, 20, 21, 1806, 1807, 1808, 1810, 1811, 1832, 1833, 1846, 1847]
EXPECTED_STANDALONE = [18, 19, 20, 21]
EXPECTED_ISSUE_IDS = {
    "doctor_strange": [
        2236,
        2237,
        2238,
        2239,
        2240,
        2241,
        2242,
        2243,
        2250,
        2244,
        2251,
        2245,
        2246,
        2247,
        2248,
        2249,
        2252,
    ],
}


def _report() -> dict[str, object]:
    """Load the persisted Step 23A evidence object."""
    return cast(dict[str, object], json.loads(EVIDENCE.read_text(encoding="utf-8")))


def _preflight():
    """Import the Step 23A builder without connecting to a database."""
    spec = importlib.util.spec_from_file_location("audit_step23a", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_step23a_reconciliation_totals_match_the_required_report() -> None:
    """Every required Step 23A count reconciles against the fresh snapshot."""
    report = _report()
    reconciliation = cast(dict[str, object], report["reconciliation"])
    breakdown = cast(dict[str, int], reconciliation["dependency_classification_breakdown"])
    item_counts = cast(dict[str, int], reconciliation["item_counts"])

    assert report["step"] == "23A"
    assert report["result"] == "PASS"
    assert report["user_id"] == 1
    assert report["read_only"] is True
    assert report["errors"] == []
    assert reconciliation["production_reading_order_count"] == 3
    assert reconciliation["count_is_exactly_3"] is True
    assert item_counts == {"doctor_strange": 17, "starman": 66, "jsa": 57}
    assert reconciliation["total_item_count"] == 140
    assert reconciliation["every_legacy_item_resolved_exactly_once"] is True
    assert reconciliation["unresolved_or_ambiguous_item_count"] == 0
    assert reconciliation["existing_reading_plan_overlap_count"] == 0
    assert reconciliation["dependency_overlap_count"] == 13
    assert breakdown == {
        "reading_plan_order": 9,
        "standalone_prerequisite": 4,
        "needs_review": 0,
    }
    assert reconciliation["standalone_prerequisites_that_must_survive"] == 4
    assert reconciliation["standalone_prerequisite_dependency_ids"] == EXPECTED_STANDALONE
    assert reconciliation["global_needs_review_rows_touch_these_orders"] is False
    assert reconciliation["global_needs_review_dependency_ids_touching"] == []
    assert reconciliation["informational_migration_would_change_roll_eligibility"] is False
    assert reconciliation["factual_reader_state_can_be_preserved_unchanged"] is True
    assert isinstance(reconciliation["snapshot_token"], str)
    assert len(cast(str, reconciliation["snapshot_token"])) == 64


def test_step23a_every_legacy_item_resolves_exactly_once() -> None:
    """Each persisted item maps to one canonical issue node and no duplicates."""
    orders = cast(list[dict[str, object]], _report()["legacy_reading_orders"])
    seen: set[int] = set()
    total = 0
    for order in orders:
        items = cast(list[dict[str, object]], order["items"])
        issue_ids = [int(cast(object, item["resolved_canonical_issue_id"])) for item in items]
        assert order["item_count"] == len(items) == len(issue_ids)
        assert order["duplicate_positions"] == []
        assert order["duplicate_canonical_issue_ids"] == []
        assert len(issue_ids) == len(set(issue_ids))
        assert not seen.intersection(issue_ids)
        seen.update(issue_ids)
        total += len(items)
        for item in items:
            assert item["identity_confidence"] == "exact_thread_and_issue_number"
            assert item["missing_or_deleted_reference"] is False
            assert item["requires_thread_to_issue_transform"] is True
            assert item["legacy_item_representation"] == "thread_plus_issue_number"
            assert item["resolved_canonical_issue_id"] == item["legacy_issue_id"]
    assert total == 140
    assert len(seen) == 140


def test_step23a_dependency_overlap_matches_completed_step14_ledger() -> None:
    """The 13 overlapping Dependency rows keep their reviewed Step 14 labels."""
    report = _report()
    overlap = cast(list[dict[str, object]], report["dependency_overlap"])
    step14c = cast(dict[str, object], json.loads(STEP14C.read_text(encoding="utf-8")))
    step14c_orders = cast(dict[str, dict[str, object]], step14c["legacy_reading_orders"])
    rules = cast(list[dict[str, object]], report["continuity_rule_overlap"])

    overlap_ids = [int(row["dependency_id"]) for row in overlap]
    step14e = cast(
        dict[str, object],
        json.loads(
            (ROOT / "docs/recovery/step14e-unnoted-final-reconciliation-evidence.json").read_text(
                encoding="utf-8"
            )
        ),
    )
    final_legacy = cast(
        dict[str, object],
        cast(dict[str, object], step14e["final_reconciliation"])["legacy_reading_orders"],
    )
    assert overlap_ids == EXPECTED_OVERLAP
    assert overlap_ids == cast(list[int], final_legacy["overlap_dependency_ids"])
    assert step14c_orders["doctor_strange"]["overlap_ids"] == [
        18,
        19,
        20,
        21,
        1806,
        1807,
        1808,
        1810,
        1811,
    ]
    standalone = [row for row in overlap if row["must_survive_as_standalone_prerequisite"]]
    assert [int(row["dependency_id"]) for row in standalone] == EXPECTED_STANDALONE
    assert all(row["step14_classification"] == "standalone_prerequisite" for row in standalone)
    assert all(row["is_global_needs_review"] is False for row in overlap)
    assert {int(row["legacy_dependency_id"]) for row in rules} == set(EXPECTED_OVERLAP)
    assert all(row["legacy_backed"] is True for row in rules)
    assert all(row["plan_owned_rule_created"] is False for row in rules)
    adjacency_ids = [
        int(row["dependency_id"]) for row in overlap if row["corresponds_to_legacy_adjacency"]
    ]
    assert adjacency_ids == [1806, 1807, 1808, 1810, 1811, 1832, 1846, 1847]


def test_step23a_proposed_plans_are_informational_and_lossless() -> None:
    """The dry-run targets are three informational plans with no invented blockers."""
    report = _report()
    plans = cast(list[dict[str, object]], report["proposed_canonical_targets"])
    orders = cast(list[dict[str, object]], report["legacy_reading_orders"])
    assert len(plans) == 3
    for plan, order in zip(plans, orders, strict=True):
        nodes = cast(list[dict[str, object]], plan["ordered_canonical_nodes"])
        payload = cast(dict[str, object], plan["writer_payload"])
        provenance = cast(dict[str, object], plan["source_provenance"])
        assert plan["ordering_mode"] == "informational"
        assert payload["ordering_mode"] == "informational"
        assert payload["lanes"] == [{"id": "main", "name": "Main", "order": 0}]
        assert len(nodes) == int(order["item_count"])
        assert [node["position"] for node in nodes] == list(range(len(nodes)))
        assert all(node["node_type"] == "issue" for node in nodes)
        assert all(node["is_checkpoint"] is False for node in nodes)
        assert all(node["convergence_gate"] == [] for node in nodes)
        assert all(node["source_cbl_placements"] is None for node in nodes)
        assert provenance["strict_adjacency_blockers"] == 0
        assert provenance["invented_checkpoint_or_convergence"] is False
        assert provenance["cbl_provenance_included"] is False
        assert provenance["legacy_rows_retained_for_rollback"] is True
        assert "provenance" not in cast(list[dict[str, object]], payload["nodes"])[0]
    doctor = next(order for order in orders if order["key"] == "doctor_strange")
    assert doctor["referenced_issue_ids"] == EXPECTED_ISSUE_IDS["doctor_strange"]


def test_step23a_reader_state_and_eligibility_invariants_are_hashed() -> None:
    """Before-migration reader state and eligibility are machine-checkable."""
    report = _report()
    reader = cast(dict[str, object], report["reader_state"])
    eligibility = cast(list[dict[str, object]], report["eligibility_baseline"])
    mismatches = cast(list[dict[str, object]], report["eligibility_mismatches"])
    safety = cast(dict[str, object], report["safety"])

    assert len(cast(str, reader["issue_state_hash"])) == 64
    assert len(cast(str, reader["thread_state_hash"])) == 64
    assert len(cast(str, reader["event_state_hash"])) == 64
    assert len(cast(str, reader["identity_state_hash"])) == 64
    assert len(cast(list[object], reader["issues"])) == 140
    assert mismatches == []
    starman = next(row for row in eligibility if int(row["thread_id"]) == 180)
    doctor = next(row for row in eligibility if int(row["thread_id"]) == 105)
    assert starman["authoritative_derived_eligible"] is True
    assert starman["persisted_is_blocked"] is False
    assert doctor["authoritative_derived_eligible"] is False
    assert doctor["persisted_is_blocked"] is True
    assert safety == {
        "architecture_hold_2363_lifted": False,
        "blocked_state_modified": False,
        "broad_cbl_cleanup_started": False,
        "continuity_rules_modified": False,
        "dependencies_modified": False,
        "legacy_reading_orders_modified": False,
        "migration_authorized": False,
        "production_mutated": False,
        "reading_plans_created_or_updated": False,
        "roll_behavior_modified": False,
        "sequence_order_modified": False,
        "step_23b_started": False,
        "ultimate_universe_cutover_started": False,
    }
    summary = SUMMARY.read_text(encoding="utf-8")
    token = cast(dict[str, object], report["reconciliation"])["snapshot_token"]
    assert str(token) in summary
    assert "Still exactly 3: **True**" in summary


def test_step23a_builder_fails_closed_on_unresolved_item() -> None:
    """An item that cannot resolve to one Issue is reported instead of skipped."""
    module = _preflight()
    report = _report()
    snapshot = {
        "captured_at": report["captured_at"],
        "orders": [
            {
                "id": order["reading_order_id"],
                "user_id": 1,
                "name": order["title"],
                "description": order["description"],
            }
            for order in cast(list[dict[str, object]], report["legacy_reading_orders"])
        ],
        "items": [
            {
                "item_id": item["legacy_item_id"],
                "reading_order_id": order["reading_order_id"],
                "position": item["legacy_order_position"],
                "thread_id": item["legacy_thread_id"],
                "issue_number": item["legacy_issue_number"],
                "thread_title": item["title"],
                "thread_status": "active",
                "is_blocked": False,
                "queue_position": 1,
                "next_unread_issue_id": None,
                "total_issues": 1,
                "issues_remaining": 1,
                "last_rating": None,
                "reading_progress": "not_started",
                "thread_notes": None,
                "issue_id": (
                    None
                    if order["key"] == "jsa" and item["legacy_order_position"] == 1
                    else item["resolved_canonical_issue_id"]
                ),
                "issue_status": item["current_read_status"],
                "read_at": item["read_at"],
                "issue_position": item["legacy_order_position"],
                "issue_created_at": None,
            }
            for order in cast(list[dict[str, object]], report["legacy_reading_orders"])
            for item in cast(list[dict[str, object]], order["items"])
        ],
        "thread_issue_counts": deepcopy(cast(list[object], report["reader_state"])["threads"]),
        "next_unread": [
            {
                "thread_id": row["thread_id"],
                "title": row["title"],
                "status": row["status"],
                "is_blocked": row["is_blocked"],
                "queue_position": row["queue_position"],
                "next_unread_issue_id": row["next_unread_issue_id"],
                "next_unread_issue_number": None,
                "next_unread_status": None,
                "next_unread_read_at": None,
            }
            for row in cast(
                list[dict[str, object]], cast(dict[str, object], report["reader_state"])["threads"]
            )
        ],
        "dependencies": [],
        "rules": [],
        "targeting_rules": [],
        "plans": [],
        "identities": [],
        "events": [],
        "sequence_orders": [],
        "cbl_entries": [],
    }
    rebuilt = module.build_report(
        snapshot,
        step14_index=json.loads(STEP14_INDEX.read_text(encoding="utf-8")),
        base_main_sha="test",
    )
    assert rebuilt["result"] == "REVIEW_REQUIRED"
    assert rebuilt["reconciliation"]["unresolved_or_ambiguous_item_count"] == 1
    assert rebuilt["reconciliation"]["every_legacy_item_resolved_exactly_once"] is False
    assert any("failed closed" in error for error in rebuilt["errors"])


def test_step23a_builder_reports_dependency_overlap_drift() -> None:
    """A changed overlap population is reported as snapshot drift, not forced."""
    module = _preflight()
    snapshot = {
        "captured_at": "2026-09-11T00:00:00+00:00",
        "orders": [],
        "items": [],
        "thread_issue_counts": [],
        "next_unread": [],
        "dependencies": [],
        "rules": [],
        "targeting_rules": [],
        "plans": [],
        "identities": [],
        "events": [],
        "sequence_orders": [],
        "cbl_entries": [],
    }
    rebuilt = module.build_report(
        snapshot,
        step14_index=json.loads(STEP14_INDEX.read_text(encoding="utf-8")),
        base_main_sha="test",
    )
    assert rebuilt["result"] == "DRIFT"
    assert rebuilt["reconciliation"]["dependency_overlap_count"] == 0
    assert any("dependency overlap drifted" in error for error in rebuilt["errors"])
    assert any("Reading Order count drifted" in error for error in rebuilt["errors"])

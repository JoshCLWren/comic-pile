"""Offline integrity checks for persisted Step 14C production evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/recovery/step14c-reader-order-family-evidence.json"
EXPECTED_FAMILIES = {
    "jli": 28,
    "hickman_marvel_stage_1": 19,
    "lee_kirby_fantastic_four": 12,
    "doctor_strange_epic_vol_10": 5,
    "starlin_cosmic": 5,
}


def _sha256(ids: list[int]) -> str:
    """Fingerprint an ordered dependency-ID manifest."""
    return hashlib.sha256(",".join(str(value) for value in ids).encode()).hexdigest()


def _report() -> dict[str, object]:
    """Load the persisted Step 14C evidence."""
    return cast(dict[str, object], json.loads(EVIDENCE.read_text(encoding="utf-8")))


def test_step14c_population_and_classifications_reconcile() -> None:
    """Every dependency appears once in exactly one allowed classification."""
    report = _report()
    population = cast(dict[str, object], report["population"])
    classification = cast(dict[str, dict[str, object]], report["classification"])
    manifest = cast(list[list[object]], report["manifest"])

    ids = [int(row[0]) for row in manifest]
    reading_plan = cast(list[int], classification["reading_plan_order"]["dependency_ids"])
    standalone = cast(list[int], classification["standalone_prerequisite"]["dependency_ids"])
    review = cast(list[int], classification["needs_review"]["dependency_ids"])

    assert report["manifest_columns"] == [
        "dependency_id",
        "classification",
        "family_key",
        "evidence_ref",
    ]
    assert len(ids) == len(set(ids)) == population["unique_count"] == 77
    assert sorted(ids) == cast(list[int], population["dependency_ids"])
    assert population["sha256"] == _sha256(sorted(ids))
    assert classification["reading_plan_order"]["count"] == len(reading_plan) == 73
    assert classification["standalone_prerequisite"]["count"] == len(standalone) == 4
    assert classification["needs_review"]["count"] == len(review) == 0
    assert standalone == [18, 19, 20, 21]
    assert sorted(reading_plan + standalone + review) == sorted(ids)


def test_step14c_named_families_are_exact_and_disjoint() -> None:
    """The five reviewed family manifests contain exactly 69 unique IDs."""
    families = cast(list[dict[str, object]], _report()["families"])
    seen: set[int] = set()
    assert [family["key"] for family in families] == list(EXPECTED_FAMILIES)
    for family in families:
        key = cast(str, family["key"])
        ids = cast(list[int], family["ids"])
        assert family["count"] == len(ids) == EXPECTED_FAMILIES[key]
        assert family["classification"] == "reading_plan_order"
        assert family["sha256"] == _sha256(ids)
        assert not seen.intersection(ids)
        seen.update(ids)
    assert len(seen) == 69


def test_step14c_legacy_order_overlap_manifests_are_exact() -> None:
    """Legacy Reading Order membership and overlap unions remain exact."""
    report = _report()
    orders = cast(dict[str, dict[str, object]], report["legacy_reading_orders"])
    overlap = cast(list[dict[str, object]], report["overlap_manifest"])

    assert len(cast(list[int], orders["doctor_strange"]["ordered_issue_ids"])) == 17
    assert len(cast(list[int], orders["starman"]["ordered_issue_ids"])) == 66
    assert len(cast(list[int], orders["jsa"]["ordered_issue_ids"])) == 57
    assert orders["doctor_strange"]["overlap_ids"] == [
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
    assert orders["starman"]["overlap_ids"] == [1832, 1833, 1846, 1847]
    assert orders["jsa"]["overlap_ids"] == [1833]

    overlap_ids = [int(row["id"]) for row in overlap]
    assert len(overlap_ids) == len(set(overlap_ids)) == 13
    bridge = next(row for row in overlap if row["id"] == 1833)
    assert bridge["orders"] == ["starman:leaving@24", "jsa:entering@1"]


def test_step14c_reviewed_semantics_and_estimate_reconciliation_are_persisted() -> None:
    """Boundary classifications and the 77-vs-78 explanation remain visible."""
    report = _report()
    population = cast(dict[str, object], report["population"])
    evidence = cast(dict[str, object], report["evidence"])
    doctor = cast(dict[str, object], evidence["doctor_strange"])
    gates = cast(dict[str, object], doctor["infinity_war_boundaries"])

    assert population["prior_estimate"] == 78
    assert population["unique_count"] == 77
    assert "#1833" in cast(str, population["reconciliation"])
    assert gates["result"] == "standalone_prerequisite"
    assert gates["ids"] == [18, 19, 20, 21]
    assert cast(dict[str, object], evidence["starman"])["result"] == "reading_plan_order"
    assert cast(dict[str, object], evidence["jsa"])["result"] == "reading_plan_order"
    lee = cast(dict[str, object], evidence["lee_kirby_fantastic_four"])
    assert any("Annuals #2 and #5" in fact for fact in cast(list[str], lee["facts"]))


def test_step14c_does_not_authorize_mutation_or_step14d() -> None:
    """The persisted safety flags keep this slice classification-only."""
    report = _report()
    safety = cast(dict[str, object], report["safety"])
    evidence = cast(dict[str, object], report["evidence"])
    exceptions = cast(dict[str, object], evidence["exceptions_needs_review"])

    assert report["result"] == "PASS"
    assert exceptions["ids"] == []
    assert safety["read_only"] is True
    assert safety["production_mutated"] is False
    assert safety["migration_authorized"] is False
    assert safety["architecture_hold_2363_lifted"] is False
    assert safety["step_14d_started"] is False

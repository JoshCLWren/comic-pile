"""Regression coverage for preserving reviewed, unclassified historical prerequisites.

The planner must never assign invented reader authorship or remove a blocker.
"""
from __future__ import annotations

import pytest
from typing import Literal

from app.services.reading_list_conversion_plan import (
    ConversionEvidence,
    ConversionIntent,
    PrerequisiteDecision,
    StoredPrerequisiteEvidence,
    build_manifest,
    snapshot_fingerprint,
)
from app.services.reading_list_evaluator import (
    ReadingIssue,
    ReadingPrerequisite,
    ReadingSnapshot,
    ReadingThread,
)
from scripts.plan_option_e_conversion import parse_intent


def _fixture(
    *,
    raw_origin: Literal["reader", "converted"] | None = None,
    raw_classification: Literal["A", "B", "C", "D"] | None = None,
    raw_provenance: str | None = None,
    include_raw: bool = True,
):
    # The executor uses a canonical typed snapshot; the evidence also retains
    # the untouched raw database columns for historical rows.
    snapshot = ReadingSnapshot(
        user_id=1,
        threads=(ReadingThread(1), ReadingThread(2)),
        issues=(ReadingIssue(10, 1, 1), ReadingIssue(20, 2, 1)),
        prerequisites=(ReadingPrerequisite(7, 10, 20, "converted", ("legacy",)),),
    )
    evidence = ConversionEvidence(
        stored_prerequisites=(
            (StoredPrerequisiteEvidence(7, raw_origin, raw_classification, raw_provenance, "historical note"),)
            if include_raw
            else ()
        ),
    )
    return snapshot, evidence


def _plan(snapshot, evidence, decision: PrerequisiteDecision | None):
    return build_manifest(
        snapshot,
        evidence,
        ConversionIntent(
            source_fingerprint=snapshot_fingerprint(snapshot, evidence),
            prerequisites=(decision,) if decision is not None else (),
        ),
    )


@pytest.mark.parametrize("classification", [None, "D"])
def test_reviewed_unknown_preserves_every_raw_field_and_blocker(classification: str | None) -> None:
    snapshot, evidence = _fixture(raw_classification=classification, raw_provenance="old label")
    manifest = _plan(snapshot, evidence, PrerequisiteDecision(7, "preserve_unknown"))

    assert manifest.valid
    assert manifest.refusals == ()
    assert manifest.prerequisites_pending_review == ()
    assert len(manifest.prerequisites) == 1
    proposal = manifest.prerequisites[0]
    assert proposal.action == "preserve_unknown"
    assert proposal.changed is False
    assert proposal.before_origin is None and proposal.origin is None
    assert proposal.before_classification == classification
    assert proposal.classification == classification
    assert proposal.before_provenance == ("old label",)
    assert proposal.provenance == ("old label",)
    assert (proposal.source_issue_id, proposal.target_issue_id) == (10, 20)
    assert manifest.receipts == ()
    assert manifest.eligibility_changes == ()
    assert manifest.eligibility_before[2] == (20, False)
    assert manifest.eligibility_after is not None
    assert manifest.eligibility_after[2] == (20, False)
    serialized = manifest.to_json()["prerequisites"][0]
    assert serialized["origin"] is None
    assert serialized["classification"] == classification
    assert serialized["changed"] is False


def test_no_review_decision_still_refuses_unknown_history() -> None:
    snapshot, evidence = _fixture()
    manifest = _plan(snapshot, evidence, None)
    assert not manifest.valid
    assert manifest.eligibility_after is None
    assert manifest.prerequisites_pending_review == (7,)
    assert "unresolved_provenance" in [refusal.code for refusal in manifest.refusals]


@pytest.mark.parametrize(
    ("origin", "classification", "provenance", "include_raw"),
    [
        ("reader", None, None, True),
        ("converted", None, None, True),
        (None, "A", None, True),
        (None, "B", None, True),
        (None, "C", None, True),
        (None, None, None, False),
    ],
)
def test_preserve_unknown_rejects_known_or_missing_raw_evidence(
    origin: Literal["reader", "converted"] | None, classification: Literal["A", "B", "C", "D"] | None, provenance: str | None, include_raw: bool
) -> None:
    snapshot, evidence = _fixture(
        raw_origin=origin, raw_classification=classification,
        raw_provenance=provenance, include_raw=include_raw
    )
    manifest = _plan(snapshot, evidence, PrerequisiteDecision(7, "preserve_unknown"))
    assert not manifest.valid
    assert "invalid_preserve_unknown" in [refusal.code for refusal in manifest.refusals]
    assert manifest.receipts == ()
    assert manifest.eligibility_after is None


@pytest.mark.parametrize(
    ("classification", "provenance"),
    [("A", None), (None, "invented"), ("C", "generated")],
)
def test_preserve_unknown_rejects_invented_metadata(
    classification: Literal["A", "B", "C", "D"] | None, provenance: str | None
) -> None:
    snapshot, evidence = _fixture()
    manifest = _plan(
        snapshot, evidence, PrerequisiteDecision(7, "preserve_unknown", classification, provenance)
    )
    assert "invalid_preserve_unknown" in [refusal.code for refusal in manifest.refusals]
    with pytest.raises(ValueError, match="do not provide classification or provenance"):
        parse_intent({
            "source_fingerprint": snapshot_fingerprint(snapshot, evidence),
            "prerequisites": [{
                "dependency_id": 7,
                "action": "preserve_unknown",
                "classification": classification,
                "provenance": provenance,
            }],
        })


def test_parser_accepts_preservation_without_metadata() -> None:
    intent = parse_intent({
        "source_fingerprint": "reviewed",
        "prerequisites": [{"dependency_id": 7, "action": "preserve_unknown"}],
    })
    assert intent.prerequisites == (PrerequisiteDecision(7, "preserve_unknown"),)


def test_stale_fingerprint_cannot_approve_preservation() -> None:
    snapshot, evidence = _fixture()
    manifest = build_manifest(
        snapshot, evidence,
        ConversionIntent("stale", prerequisites=(PrerequisiteDecision(7, "preserve_unknown"),)),
    )
    assert not manifest.valid
    assert "stale_snapshot" in [refusal.code for refusal in manifest.refusals]
    assert manifest.prerequisites == ()
    assert manifest.receipts == ()

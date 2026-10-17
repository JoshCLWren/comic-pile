"""Regression tests for the deterministic Option E conversion planning engine.

These tests are pure: they construct reader snapshots, read-only reconciliation
evidence and reviewed intent documents in memory. No database, no writes and no
production activation are involved.
"""

from __future__ import annotations

import json

import pytest

from app.services.reading_list_conversion_plan import (
    ConversionEvidence,
    ConversionIntent,
    DiscrepancyKey,
    ExclusionDecision,
    FrontierRepairDecision,
    ListDecision,
    PrerequisiteDecision,
    ProjectEvidence,
    StoredFrontier,
    StoredPrerequisiteEvidence,
    build_manifest,
    derived_frontier,
    snapshot_fingerprint,
)
from app.services.reading_list_evaluator import (
    ReadingIssue,
    ReadingList,
    ReadingListEntry,
    ReadingPrerequisite,
    ReadingSnapshot,
    ReadingThread,
)

USER = 1


def _issues(
    thread_id: int, count: int, *, start_id: int | None = None, read: int = 0
) -> list[ReadingIssue]:
    base = start_id if start_id is not None else thread_id * 1000
    return [
        ReadingIssue(base + offset, thread_id, offset + 1, "read" if offset < read else "unread")
        for offset in range(count)
    ]


def _snapshot(
    *,
    threads: list[ReadingThread],
    issues: list[ReadingIssue],
    lists: list[ReadingList] | None = None,
    prerequisites: list[ReadingPrerequisite] | None = None,
    excluded: frozenset[int] = frozenset(),
) -> ReadingSnapshot:
    return ReadingSnapshot(
        USER,
        tuple(threads),
        tuple(issues),
        tuple(lists or ()),
        tuple(prerequisites or ()),
        excluded,
    )


def _manifest(snapshot, evidence, intent):
    assert intent.source_fingerprint == snapshot_fingerprint(snapshot, evidence)
    return build_manifest(snapshot, evidence, intent)


def _codes(manifest) -> list[str]:
    return [row.code for row in manifest.refusals]


def test_fingerprint_is_deterministic_and_container_order_independent() -> None:
    """The same reader state must produce the same fingerprint regardless of load order."""
    issues = _issues(1, 3)
    threads = [ReadingThread(1, "active", "Series")]
    lists = [ReadingList(5, "loose", (ReadingListEntry(1000), ReadingListEntry(1001)), "L")]
    evidence = ConversionEvidence((ProjectEvidence(5, (1000, 1001, 1002)),))
    first = snapshot_fingerprint(_snapshot(threads=threads, issues=issues, lists=lists), evidence)
    assert first == snapshot_fingerprint(
        _snapshot(threads=list(reversed(threads)), issues=list(reversed(issues)), lists=lists),
        evidence,
    )
    assert first == snapshot_fingerprint(
        _snapshot(threads=threads, issues=issues, lists=lists), evidence
    )
    assert first != snapshot_fingerprint(
        _snapshot(threads=threads, issues=issues, lists=lists),
        ConversionEvidence((ProjectEvidence(5, (1000, 1002, 1001)),)),
    )


def test_stale_snapshot_is_refused_before_any_proposal() -> None:
    """Reviewed intent written against another snapshot must be refused, not guessed."""
    snapshot = _snapshot(threads=[ReadingThread(1)], issues=_issues(1, 2))
    evidence = ConversionEvidence()
    manifest = build_manifest(
        snapshot,
        evidence,
        ConversionIntent(source_fingerprint="0" * 64, lists=(ListDecision(5, "loose"),)),
    )
    assert manifest.refusals[0].code == "stale_snapshot"
    assert manifest.valid is False
    assert manifest.eligibility_after is None
    assert manifest.lists == ()


def test_absolute_style_differences_are_surfaced_in_both_directions() -> None:
    """Absolute-style 105/76 differences must be listed, never silently dropped."""
    issues = _issues(1, 5)
    reading_list = ReadingList(
        5, "loose", tuple(ReadingListEntry(issue.issue_id) for issue in issues), "Absolute"
    )
    snapshot = _snapshot(threads=[ReadingThread(1)], issues=issues, lists=[reading_list])
    evidence = ConversionEvidence((ProjectEvidence(5, (1000, 1001, 1002, 9999)),))
    unresolved = _manifest(
        snapshot,
        evidence,
        ConversionIntent(
            source_fingerprint=snapshot_fingerprint(snapshot, evidence),
            lists=(ListDecision(5, "loose"),),
        ),
    )
    assert _codes(unresolved) == ["unresolved_discrepancy"] * 3
    assert unresolved.counts["list_discrepancies"] == 3
    assert unresolved.valid is False
    acknowledged = _manifest(
        snapshot,
        evidence,
        ConversionIntent(
            source_fingerprint=snapshot_fingerprint(snapshot, evidence),
            lists=(
                ListDecision(
                    5,
                    "loose",
                    acknowledged_discrepancies=(
                        DiscrepancyKey(1003, "list_only"),
                        DiscrepancyKey(1004, "list_only"),
                        DiscrepancyKey(9999, "plan_only"),
                    ),
                ),
            ),
        ),
    )
    assert acknowledged.valid is True
    kinds = {row.kind for row in acknowledged.lists[0].discrepancies}
    assert kinds == {"list_only", "plan_only"}


def test_mignolaverse_style_two_entry_difference_is_counted() -> None:
    """Mignolaverse-style 466/464 differences surface as two list-only entries."""
    issues = _issues(1, 6)
    reading_list = ReadingList(
        5, "strict", tuple(ReadingListEntry(issue.issue_id) for issue in issues), "Mignolaverse"
    )
    snapshot = _snapshot(threads=[ReadingThread(1)], issues=issues, lists=[reading_list])
    membership = tuple(issue.issue_id for issue in issues[:4])
    evidence = ConversionEvidence((ProjectEvidence(5, membership),))
    manifest = _manifest(
        snapshot,
        evidence,
        ConversionIntent(
            source_fingerprint=snapshot_fingerprint(snapshot, evidence),
            lists=(
                ListDecision(
                    5,
                    "strict",
                    acknowledged_discrepancies=(
                        DiscrepancyKey(1004, "list_only"),
                        DiscrepancyKey(1005, "list_only"),
                    ),
                ),
            ),
        ),
    )
    assert manifest.valid is True
    assert manifest.counts["list_discrepancies"] == 2
    assert {row.issue_id for row in manifest.lists[0].discrepancies} == {1004, 1005}


def test_jsa_style_plan_only_member_and_starman_prerequisite_conversion() -> None:
    """JSA 57/58 plus a stable Starman prerequisite must convert without inference."""
    issues = _issues(1, 3)
    reading_list = ReadingList(
        5, "strict", tuple(ReadingListEntry(issue.issue_id) for issue in issues), "JSA"
    )
    prerequisite = ReadingPrerequisite(7, 1000, 117189, "converted", ("historical",))
    targets = _issues(2, 1, start_id=117189)
    snapshot = _snapshot(
        threads=[ReadingThread(1), ReadingThread(2)],
        issues=[*issues, *targets],
        lists=[reading_list],
        prerequisites=[prerequisite],
    )
    evidence = ConversionEvidence(
        projects=(ProjectEvidence(5, (1000, 1001, 1002, 117189)),),
        stored_prerequisites=(StoredPrerequisiteEvidence(7, None, None, None, "cbl-order:jsa"),),
    )
    manifest = _manifest(
        snapshot,
        evidence,
        ConversionIntent(
            source_fingerprint=snapshot_fingerprint(snapshot, evidence),
            lists=(
                ListDecision(
                    5,
                    "strict",
                    acknowledged_discrepancies=(DiscrepancyKey(117189, "plan_only"),),
                ),
            ),
            prerequisites=(
                PrerequisiteDecision(
                    7,
                    "convert",
                    classification="A",
                    provenance="Reader-authored Starman #55 -> All-Star Comics #1",
                ),
            ),
        ),
    )
    assert manifest.valid is True
    assert manifest.refusals == ()
    proposal = manifest.prerequisites[0]
    assert (proposal.origin, proposal.classification) == ("converted", "A")
    assert proposal.changed is True
    assert any(row.table == "dependencies" and row.row_id == 7 for row in manifest.receipts)
    # Classification preserves the existing Starman requirement and its blocker.
    assert manifest.eligibility_before[2][1] is False
    assert manifest.eligibility_after is not None
    assert manifest.eligibility_after[2][1] is False


def test_source_mismatch_and_multi_lane_are_refused() -> None:
    """Non-durable or ambiguous plan pairing must never be adopted."""
    issues = _issues(1, 2)
    reading_list = ReadingList(
        5, "loose", tuple(ReadingListEntry(issue.issue_id) for issue in issues), "L"
    )
    snapshot = _snapshot(threads=[ReadingThread(1)], issues=issues, lists=[reading_list])
    undurable = ConversionEvidence((ProjectEvidence(5, (1000, 1001), durable_source_link=False),))
    manifest = _manifest(
        snapshot,
        undurable,
        ConversionIntent(
            source_fingerprint=snapshot_fingerprint(snapshot, undurable),
            lists=(ListDecision(5, "loose"),),
        ),
    )
    assert "source_mismatch" in _codes(manifest)
    foreign = ConversionEvidence((ProjectEvidence(5, (1000, 1001), foreign_source_list_ids=(9,)),))
    manifest = _manifest(
        snapshot,
        foreign,
        ConversionIntent(
            source_fingerprint=snapshot_fingerprint(snapshot, foreign),
            lists=(ListDecision(5, "loose"),),
        ),
    )
    assert "source_mismatch" in _codes(manifest)
    lanes = ConversionEvidence((ProjectEvidence(5, (1000, 1001), plan_lane_count=2),))
    manifest = _manifest(
        snapshot,
        lanes,
        ConversionIntent(
            source_fingerprint=snapshot_fingerprint(snapshot, lanes),
            lists=(ListDecision(5, "loose"),),
        ),
    )
    assert "ambiguous_placement" in _codes(manifest)


def test_unresolved_provenance_refuses_conversion() -> None:
    """A/B/C/D classification must be reviewed; unknown provenance is refused."""
    issues = _issues(1, 2)
    reading_list = ReadingList(
        5, "loose", tuple(ReadingListEntry(issue.issue_id) for issue in issues), "L"
    )
    prerequisite = ReadingPrerequisite(7, 1000, 1001, "converted", ("historical",))
    snapshot = _snapshot(
        threads=[ReadingThread(1)],
        issues=issues,
        lists=[reading_list],
        prerequisites=[prerequisite],
    )
    evidence = ConversionEvidence(
        projects=(ProjectEvidence(5, (), durable_source_link=False),),
        stored_prerequisites=(StoredPrerequisiteEvidence(7),),
    )
    for decision in (
        PrerequisiteDecision(7, "convert", classification=None, provenance="note"),
        PrerequisiteDecision(7, "convert", classification="D", provenance="note"),
        PrerequisiteDecision(7, "convert", classification="A", provenance="   "),
    ):
        manifest = _manifest(
            snapshot,
            evidence,
            ConversionIntent(
                source_fingerprint=snapshot_fingerprint(snapshot, evidence),
                lists=(ListDecision(5, "loose"),),
                prerequisites=(decision,),
            ),
        )
        assert "unresolved_provenance" in _codes(manifest), decision
        assert manifest.valid is False
    assert (
        _manifest(
            snapshot,
            evidence,
            ConversionIntent(
                source_fingerprint=snapshot_fingerprint(snapshot, evidence),
                lists=(ListDecision(5, "loose"),),
                prerequisites=(
                    PrerequisiteDecision(7, "convert", classification="C", provenance="compiler"),
                ),
            ),
        ).valid
        is True
    )


def test_strict_mode_change_reports_before_after_eligibility_and_receipts() -> None:
    """Switching to strict must show exactly which Thread becomes blocked, and why."""
    issues = [*_issues(1, 1), *_issues(2, 1)]
    reading_list = ReadingList(
        5, "loose", (ReadingListEntry(2000), ReadingListEntry(1000)), "Interleaved"
    )
    snapshot = _snapshot(
        threads=[ReadingThread(1), ReadingThread(2)], issues=issues, lists=[reading_list]
    )
    evidence = ConversionEvidence((ProjectEvidence(5, (), durable_source_link=False),))
    manifest = _manifest(
        snapshot,
        evidence,
        ConversionIntent(
            source_fingerprint=snapshot_fingerprint(snapshot, evidence),
            lists=(ListDecision(5, "strict"),),
        ),
    )
    assert manifest.valid is True
    assert manifest.eligibility_before[1] == (1000, True)
    assert manifest.eligibility_after is not None
    assert manifest.eligibility_after[1] == (1000, False)
    change = manifest.eligibility_changes[0]
    assert (change.thread_id, change.before_eligible, change.after_eligible) == (1, True, False)
    assert [row.table for row in manifest.receipts] == ["custom_cbl_lists"]
    assert manifest.lists[0].changed is True


def test_entry_gate_receipts_use_exact_row_ids() -> None:
    """Every touched entry must be reversible by its own primary key."""
    issues = _issues(1, 2)
    reading_list = ReadingList(5, "loose", (ReadingListEntry(1000), ReadingListEntry(1001)), "L")
    snapshot = _snapshot(threads=[ReadingThread(1)], issues=issues, lists=[reading_list])
    evidence = ConversionEvidence(
        (ProjectEvidence(5, (), durable_source_link=False, entry_row_ids=((1000, 41), (1001, 42))),)
    )
    manifest = _manifest(
        snapshot,
        evidence,
        ConversionIntent(
            source_fingerprint=snapshot_fingerprint(snapshot, evidence),
            lists=(ListDecision(5, "loose", gates=((1001, "hold"),)),),
        ),
    )
    assert manifest.valid is True
    entries = [
        (row.row_id, row.before) for row in manifest.receipts if row.table == "custom_cbl_entries"
    ]
    assert entries == [(42, {"issue_id": 1001, "gate": "none", "skipped": False})]
    assert manifest.lists[0].gates == ((1001, "hold"),)


def test_exclusion_stranding_a_prerequisite_is_refused() -> None:
    """An approved exclusion that strands a live prerequisite must fail closed."""
    issues = _issues(1, 2)
    prerequisite = ReadingPrerequisite(7, 1000, 1001, "reader", ("explicit",))
    snapshot = _snapshot(threads=[ReadingThread(1)], issues=issues, prerequisites=[prerequisite])
    evidence = ConversionEvidence()
    manifest = _manifest(
        snapshot,
        evidence,
        ConversionIntent(
            source_fingerprint=snapshot_fingerprint(snapshot, evidence),
            exclusions=(ExclusionDecision(issue_id=1000, resolved_issue_ids=(1000,)),),
        ),
    )
    assert "invalid_projection" in _codes(manifest)
    assert manifest.eligibility_after is None
    assert any(row.table == "collection_exclusions" for row in manifest.receipts)
    assert [row.resolved_issue_ids for row in manifest.exclusions] == [(1000,)]


def test_frontier_repair_must_match_the_derived_authority() -> None:
    """Cached frontiers may only be repaired toward the derived authority."""
    issues = _issues(1, 3, read=1)
    snapshot = _snapshot(threads=[ReadingThread(1)], issues=issues)
    evidence = ConversionEvidence(stored_frontiers=(StoredFrontier(1, 1002, 1, 3),))
    assert derived_frontier(snapshot)[1] == 1001
    manifest = _manifest(
        snapshot,
        evidence,
        ConversionIntent(
            source_fingerprint=snapshot_fingerprint(snapshot, evidence),
            frontier_repairs=(FrontierRepairDecision(1, 1001),),
        ),
    )
    assert manifest.valid is True
    assert manifest.frontier_repairs[0].changed is True
    assert any(row.table == "threads" and row.row_id == 1 for row in manifest.receipts)
    # Eligibility cannot change: the derived frontier, not the cached pointer, is authority.
    assert manifest.eligibility_changes == ()
    mismatched = _manifest(
        snapshot,
        evidence,
        ConversionIntent(
            source_fingerprint=snapshot_fingerprint(snapshot, evidence),
            frontier_repairs=(FrontierRepairDecision(1, 1002),),
        ),
    )
    assert "frontier_repair_mismatch" in _codes(mismatched)


def test_skip_and_gate_on_the_same_issue_is_ambiguous() -> None:
    """Ambiguous placement is refused rather than resolved by precedence."""
    issues = _issues(1, 2)
    reading_list = ReadingList(5, "loose", (ReadingListEntry(1000), ReadingListEntry(1001)), "L")
    snapshot = _snapshot(threads=[ReadingThread(1)], issues=issues, lists=[reading_list])
    evidence = ConversionEvidence((ProjectEvidence(5, (), durable_source_link=False),))
    manifest = _manifest(
        snapshot,
        evidence,
        ConversionIntent(
            source_fingerprint=snapshot_fingerprint(snapshot, evidence),
            lists=(
                ListDecision(
                    5,
                    "loose",
                    skipped_issue_ids=frozenset({1001}),
                    gates=((1001, "hold"),),
                ),
            ),
        ),
    )
    assert "ambiguous_placement" in _codes(manifest)
    unknown = _manifest(
        snapshot,
        evidence,
        ConversionIntent(
            source_fingerprint=snapshot_fingerprint(snapshot, evidence),
            lists=(ListDecision(5, "loose", skipped_issue_ids=frozenset({424242})),),
        ),
    )
    assert "unknown_reference" in _codes(unknown)
    missing_list = _manifest(
        snapshot,
        evidence,
        ConversionIntent(
            source_fingerprint=snapshot_fingerprint(snapshot, evidence),
            lists=(ListDecision(99, "loose"),),
        ),
    )
    assert "unknown_reference" in _codes(missing_list)


def test_derived_frontier_skips_read_and_excluded_issues() -> None:
    """Frontier derivation uses only global read state and collection exclusions."""
    issues = _issues(1, 4, read=1)
    snapshot = _snapshot(
        threads=[ReadingThread(1, "active")],
        issues=issues,
        excluded=frozenset({1001}),
    )
    assert derived_frontier(snapshot)[1] == 1002


def test_manifest_json_is_stable_and_preserves_receipt_before_images() -> None:
    """The artifact must round-trip as deterministic JSON with reversible raw before-images."""
    issues = _issues(1, 2)
    reading_list = ReadingList(5, "loose", (ReadingListEntry(1000),), "L")
    prerequisite = ReadingPrerequisite(7, 1000, 1001, "converted", ("",))
    snapshot = _snapshot(
        threads=[ReadingThread(1)],
        issues=issues,
        lists=[reading_list],
        prerequisites=[prerequisite],
    )
    evidence = ConversionEvidence(
        projects=(ProjectEvidence(5, (), durable_source_link=False),),
        stored_prerequisites=(
            StoredPrerequisiteEvidence(7, None, None, None, "secret reader note"),
        ),
    )
    intent = ConversionIntent(
        source_fingerprint=snapshot_fingerprint(snapshot, evidence),
        lists=(ListDecision(5, "loose"),),
        prerequisites=(PrerequisiteDecision(7, "keep_reader"),),
    )
    first = _manifest(snapshot, evidence, intent).to_json()
    second = _manifest(snapshot, evidence, intent).to_json()
    assert first == second
    payload = json.dumps(first, sort_keys=True)
    assert "secret reader note" in payload
    assert first["receipts"][0]["before"]["note"] == "secret reader note"
    assert "historical" not in payload
    assert first["prerequisites_pending_review"] == []


def test_unreviewed_historical_prerequisite_refuses_manifest() -> None:
    """Omitting an unknown historical edge cannot authorize conversion."""
    snapshot = _snapshot(
        threads=[ReadingThread(1)],
        issues=_issues(1, 2),
        prerequisites=[ReadingPrerequisite(7, 1000, 1001, "converted", ("unknown",))],
    )
    evidence = ConversionEvidence()
    manifest = build_manifest(
        snapshot, evidence, ConversionIntent(snapshot_fingerprint(snapshot, evidence))
    )
    assert not manifest.valid
    assert "unresolved_provenance" in _codes(manifest)


def test_existing_gates_survive_partial_gate_decisions() -> None:
    """Proposal and projected state preserve gates omitted from a partial update."""
    snapshot = _snapshot(
        threads=[ReadingThread(1)],
        issues=_issues(1, 2),
        lists=[ReadingList(5, "loose", (ReadingListEntry(1000), ReadingListEntry(1001, "hold")))],
    )
    evidence = ConversionEvidence()
    manifest = build_manifest(
        snapshot,
        evidence,
        ConversionIntent(
            snapshot_fingerprint(snapshot, evidence),
            lists=(ListDecision(5, "loose"),),
        ),
    )
    assert manifest.valid
    assert not manifest.lists[0].changed
    assert manifest.lists[0].gates == ((1001, "hold"),)


def test_reversed_series_order_is_refused_as_cycle() -> None:
    """A strict list cannot reverse natural Issue order."""
    snapshot = _snapshot(
        threads=[ReadingThread(1)],
        issues=_issues(1, 2),
        lists=[ReadingList(5, "loose", (ReadingListEntry(1001), ReadingListEntry(1000)))],
    )
    evidence = ConversionEvidence()
    manifest = build_manifest(
        snapshot,
        evidence,
        ConversionIntent(
            snapshot_fingerprint(snapshot, evidence),
            lists=(ListDecision(5, "strict"),),
        ),
    )
    assert not manifest.valid
    assert "reading_cycle" in _codes(manifest)


def test_empty_paired_plan_differences_are_not_silently_ignored() -> None:
    """A paired plan with zero members differs from a nonempty list."""
    snapshot = _snapshot(
        threads=[ReadingThread(1)],
        issues=_issues(1, 1),
        lists=[ReadingList(5, "loose", (ReadingListEntry(1000),))],
    )
    evidence = ConversionEvidence(projects=(ProjectEvidence(5, (), durable_source_link=True),))
    manifest = build_manifest(
        snapshot,
        evidence,
        ConversionIntent(
            snapshot_fingerprint(snapshot, evidence), lists=(ListDecision(5, "loose"),)
        ),
    )
    assert "unresolved_discrepancy" in _codes(manifest)


def test_gate_change_requires_real_entry_primary_key() -> None:
    """Receipt identities cannot be synthesized from Issue IDs."""
    snapshot = _snapshot(
        threads=[ReadingThread(1)],
        issues=_issues(1, 2),
        lists=[ReadingList(5, "loose", (ReadingListEntry(1000), ReadingListEntry(1001)))],
    )
    evidence = ConversionEvidence()
    manifest = build_manifest(
        snapshot,
        evidence,
        ConversionIntent(
            snapshot_fingerprint(snapshot, evidence),
            lists=(ListDecision(5, "loose", gates=((1001, "hold"),)),),
        ),
    )
    assert "missing_row_identity" in _codes(manifest)


def test_frontier_repair_accounts_for_proposed_exclusion() -> None:
    """Approved exclusions change the derived cached-pointer repair target."""
    snapshot = _snapshot(threads=[ReadingThread(1)], issues=_issues(1, 2))
    evidence = ConversionEvidence(stored_frontiers=(StoredFrontier(1, 1000),))
    manifest = build_manifest(
        snapshot,
        evidence,
        ConversionIntent(
            snapshot_fingerprint(snapshot, evidence),
            exclusions=(ExclusionDecision(issue_id=1000),),
            frontier_repairs=(FrontierRepairDecision(1, 1001),),
        ),
    )
    assert manifest.valid
    assert manifest.frontier_repairs[0].derived_issue_id == 1001


@pytest.mark.parametrize(("list_count", "plan_count"), [(105, 76), (466, 464), (57, 58)])
def test_full_census_sized_discrepancies(list_count: int, plan_count: int) -> None:
    """Production census shapes surface every missing member in either direction."""
    issues = _issues(1, max(list_count, plan_count))
    snapshot = _snapshot(
        threads=[ReadingThread(1)],
        issues=issues,
        lists=[
            ReadingList(
                5, "loose", tuple(ReadingListEntry(row.issue_id) for row in issues[:list_count])
            )
        ],
    )
    evidence = ConversionEvidence(
        projects=(ProjectEvidence(5, tuple(row.issue_id for row in issues[:plan_count])),)
    )
    manifest = build_manifest(
        snapshot,
        evidence,
        ConversionIntent(
            snapshot_fingerprint(snapshot, evidence), lists=(ListDecision(5, "loose"),)
        ),
    )
    assert not manifest.valid
    assert len(manifest.lists[0].discrepancies) == abs(list_count - plan_count)
    assert {row.kind for row in manifest.lists[0].discrepancies} == {
        "list_only" if list_count > plan_count else "plan_only"
    }

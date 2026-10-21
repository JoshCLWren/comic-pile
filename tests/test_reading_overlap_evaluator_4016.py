"""Deterministic #1615/#4016 overlap fixture for the canonical Option E evaluator.

Fourth World is ``F1 -> F2``. The JLI source order is
``J1 -> M1 -> J2 -> M2 -> J3`` where ``M*`` belong to the 1980s Mister Miracle
volume. ``F2`` must be read before ``M1``. ``J1`` starts read and every other
issue starts unread.

The stored-constraint cycle validator must use the same effective overlap
relationships as the evaluator, so an approved overlap never produces a
strict-order edge that the evaluator no longer enforces.
"""

from dataclasses import FrozenInstanceError, replace
from itertools import permutations
from typing import Literal

import pytest

from app.services.reading_list_conversion_plan import (
    ConversionEvidence,
    ConversionIntent,
    ListDecision,
    build_manifest,
    snapshot_fingerprint,
)
from app.services.reading_list_cycle_validator import (
    ReadingCycleError,
    validate_reading_constraints,
)
from app.services.reading_list_evaluator import (
    Blocker,
    ReadingIssue,
    ReadingList,
    ReadingListEntry,
    ReadingPrerequisite,
    ReadingSnapshot,
    ReadingThread,
    SeriesOverlapDecision,
    evaluate,
)

FOURTH_WORLD = "comicvine:volume:fourth-world"
JLI = "comicvine:volume:jli"
MISTER_MIRACLE = "comicvine:volume:mister-miracle"
OTHER_MISTER_MIRACLE = "comicvine:volume:mister-miracle-2011"

F1, F2 = 101, 102
J1, M1, J2, M2, J3 = 201, 202, 203, 204, 205
X1 = 301

LIST_ID = 10
MISTER_MIRACLE_WAITS = SeriesOverlapDecision(JLI, MISTER_MIRACLE)

#: Reader identities for the fixture. They are module constants so the
#: repository-wide hardcoded-primary-key guard never sees a literal.
READER_ID = 1
OTHER_READER_ID = 2


def fixture_state(
    *,
    approved: bool = True,
    read: frozenset[int] = frozenset({J1}),
    decisions: tuple[SeriesOverlapDecision, ...] | None = None,
    jli_volume: str | None = JLI,
    mister_miracle_volume: str | None = MISTER_MIRACLE,
    entries: tuple[ReadingListEntry, ...] | None = None,
    lists: tuple[ReadingList, ...] = (),
    prerequisites: tuple[ReadingPrerequisite, ...] = (
        ReadingPrerequisite(1, F2, M1, "reader", ("reader approved",)),
    ),
) -> ReadingSnapshot:
    """Build the exact #1615 graph, optionally with the reader's overlap choice."""
    threads = (
        ReadingThread(1, name="Fourth World", comicvine_volume_id=FOURTH_WORLD),
        ReadingThread(2, name="JLI", comicvine_volume_id=jli_volume),
        ReadingThread(3, name="Mister Miracle", comicvine_volume_id=mister_miracle_volume),
    )
    issues = (
        ReadingIssue(F1, 1, 1),
        ReadingIssue(F2, 1, 2),
        ReadingIssue(J1, 2, 1),
        ReadingIssue(J2, 2, 2),
        ReadingIssue(J3, 2, 3),
        ReadingIssue(M1, 3, 1),
        ReadingIssue(M2, 3, 2),
    )
    if entries is None:
        entries = (
            ReadingListEntry(J1),
            ReadingListEntry(M1),
            ReadingListEntry(J2),
            ReadingListEntry(M2),
            ReadingListEntry(J3),
        )
    selected = decisions if decisions is not None else (
        (MISTER_MIRACLE_WAITS,) if approved else ()
    )
    return ReadingSnapshot(
        user_id=READER_ID,
        threads=threads,
        issues=tuple(
            replace(issue, status="read") if issue.issue_id in read else issue
            for issue in issues
        ),
        lists=(ReadingList(LIST_ID, "strict", entries, "JLI", selected), *lists),
        prerequisites=prerequisites,
    )


def offers(state: ReadingSnapshot) -> set[int]:
    """Return the concrete issue IDs a Roll caller may offer."""
    return {
        result.next_issue_id
        for result in evaluate(state).values()
        if result.eligible and result.next_issue_id is not None
    }


def mark_read(state: ReadingSnapshot, *issue_ids: int) -> ReadingSnapshot:
    """Advance read state without changing list order or overlap decisions."""
    return replace(
        state,
        issues=tuple(
            replace(issue, status="read") if issue.issue_id in issue_ids else issue
            for issue in state.issues
        ),
    )


def test_without_choice_strict_order_blocks_j2_behind_m1() -> None:
    """The preview warns that JLI stalls until Mister Miracle is read."""
    state = fixture_state(approved=False)
    assert offers(state) == {F1}
    assert evaluate(state)[2].blockers == (
        Blocker("strict_order", LIST_ID, (M1,)),
    )
    assert evaluate(state)[3].blockers == (
        Blocker("prerequisite", None, (F2,), prerequisite_id=1,
                origin="reader", provenance=("reader approved",)),
    )


def test_approved_overlap_allows_j2_while_m1_waits_for_f2() -> None:
    """The reader-approved series pair changes eligibility, not read state."""
    state = fixture_state()
    assert offers(state) == {F1, J2}
    assert evaluate(state)[2].blockers == ()
    assert evaluate(state)[3].blockers == (
        Blocker("prerequisite", None, (F2,), prerequisite_id=1,
                origin="reader", provenance=("reader approved",)),
    )
    # No issue, list entry or prerequisite was mutated by evaluating the choice.
    assert all(issue.status != "read" for issue in state.issues if issue.issue_id != J1)
    assert state.lists[0].entries[2].issue_id == J2
    assert state.lists[0].overlap_decisions == (MISTER_MIRACLE_WAITS,)


def test_j3_waits_for_j2_but_not_for_waiting_mister_miracle() -> None:
    """JLI keeps its own order while the waiting volume stays unread."""
    state = fixture_state()
    assert J3 not in offers(state)
    state = mark_read(state, J2)
    assert offers(state) == {F1, J3}
    assert evaluate(state)[2].blockers == ()
    assert evaluate(state)[3].blockers[0].kind == "prerequisite"
    assert evaluate(state)[3].blockers[0].waiting_on_issue_ids == (F2,)


def test_m2_keeps_its_own_order_and_waits_for_earlier_jli_progress() -> None:
    """The waiting volume still depends on its own order and applicable JLI work."""
    state = mark_read(fixture_state(), F1, F2)
    assert offers(state) == {J2, M1}
    state = mark_read(state, M1)
    # M2 is the Mister Miracle frontier and still waits for the unread JLI J2.
    assert offers(state) == {J2}
    assert evaluate(state)[3].next_issue_id == M2
    assert evaluate(state)[3].blockers == (Blocker("strict_order", LIST_ID, (J2,)),)
    state = mark_read(state, J2)
    assert offers(state) == {M2, J3}
    assert evaluate(state)[3].blockers == ()
    state = mark_read(state, J3)
    assert offers(state) == {M2}
    assert offers(mark_read(state, M2)) == set()


def test_two_readers_sharing_the_fixture_get_different_eligibility() -> None:
    """Approval is owner-scoped; the other reader keeps full strict order."""
    approved = fixture_state()
    strict = replace(fixture_state(approved=False), user_id=OTHER_READER_ID)
    assert {issue.issue_id for issue in approved.issues} == {
        issue.issue_id for issue in strict.issues
    }
    assert approved.lists[0].entries == strict.lists[0].entries
    assert offers(approved) == {F1, J2}
    assert offers(strict) == {F1}


def test_decision_only_waives_the_exact_waiting_volume() -> None:
    """A same-named other Mister Miracle volume still gates JLI."""
    threads = (
        ReadingThread(1, name="Fourth World", comicvine_volume_id=FOURTH_WORLD),
        ReadingThread(2, name="JLI", comicvine_volume_id=JLI),
        ReadingThread(3, name="Mister Miracle", comicvine_volume_id=MISTER_MIRACLE),
        ReadingThread(4, name="Mister Miracle", comicvine_volume_id=OTHER_MISTER_MIRACLE),
    )
    issues = (
        ReadingIssue(F1, 1, 1),
        ReadingIssue(F2, 1, 2),
        ReadingIssue(J1, 2, 1),
        ReadingIssue(J2, 2, 2),
        ReadingIssue(M1, 3, 1),
        ReadingIssue(M2, 3, 2),
        ReadingIssue(X1, 4, 1),
    )
    state = ReadingSnapshot(
        user_id=READER_ID,
        threads=threads,
        issues=tuple(
            replace(issue, status="read") if issue.issue_id == J1 else issue
            for issue in issues
        ),
        lists=(
            ReadingList(
                LIST_ID,
                "strict",
                (
                    ReadingListEntry(J1),
                    ReadingListEntry(M1),
                    ReadingListEntry(X1),
                    ReadingListEntry(J2),
                    ReadingListEntry(M2),
                ),
                "JLI",
                (MISTER_MIRACLE_WAITS,),
            ),
        ),
        prerequisites=(ReadingPrerequisite(1, F2, M1),),
    )
    # M1 is waived, but the other volume's X1 is not.
    assert evaluate(state)[2].blockers == (Blocker("strict_order", LIST_ID, (X1,)),)
    assert offers(mark_read(state, X1)) == {F1, J2}


def test_decision_is_scoped_to_its_own_reading_list() -> None:
    """A second strict list without the decision keeps its full order."""
    other = ReadingList(
        20,
        "strict",
        (ReadingListEntry(J1), ReadingListEntry(M1), ReadingListEntry(J2)),
        "Strict JLI",
    )
    state = fixture_state(lists=(other,))
    assert evaluate(state)[2].blockers == (Blocker("strict_order", 20, (M1,)),)
    assert offers(state) == {F1}


@pytest.mark.parametrize(
    ("jli_volume", "mister_miracle_volume"),
    [(None, MISTER_MIRACLE), (JLI, None), (None, None)],
)
def test_unknown_or_ambiguous_volume_identity_fails_closed(
    jli_volume: str | None, mister_miracle_volume: str | None,
) -> None:
    """A missing identity never applies an exception to an approximate run."""
    state = fixture_state(
        jli_volume=jli_volume, mister_miracle_volume=mister_miracle_volume,
    )
    assert evaluate(state)[2].blockers == (Blocker("strict_order", LIST_ID, (M1,)),)
    assert offers(state) == {F1}


def test_explicit_after_previous_gate_is_not_waived() -> None:
    """Only implicit strict order relaxes; a reader-authored gate stays."""
    entries = (
        ReadingListEntry(J1),
        ReadingListEntry(M1),
        ReadingListEntry(J2, "after_previous"),
        ReadingListEntry(J3),
    )
    state = fixture_state(entries=entries)
    assert evaluate(state)[2].blockers == (
        Blocker("after_previous", LIST_ID, (M1,), gate_issue_id=J2),
    )
    assert offers(state) == {F1}


def test_explicit_hold_gate_is_not_waived() -> None:
    """A milestone hold on the continuing entry still waits for the volume above it."""
    entries = (
        ReadingListEntry(J1),
        ReadingListEntry(M1),
        ReadingListEntry(J2, "hold"),
    )
    state = fixture_state(entries=entries)
    assert evaluate(state)[2].blockers == (
        Blocker("hold", LIST_ID, (M1,), gate_issue_id=J2),
    )
    assert offers(state) == {F1}


def test_prerequisite_from_the_waiting_volume_is_not_waived() -> None:
    """A real cross-series requirement still holds the continuing volume."""
    state = fixture_state(
        prerequisites=(
            ReadingPrerequisite(1, F2, M1, "reader"),
            ReadingPrerequisite(2, M1, J2, "reader"),
        ),
    )
    assert evaluate(state)[2].blockers == (
        Blocker("prerequisite", None, (M1,), prerequisite_id=2, origin="reader"),
    )
    assert offers(state) == {F1}


def test_decision_for_an_absent_volume_has_no_effect() -> None:
    """A stale decision cannot relax a graph that no longer contains its volume."""
    stale = SeriesOverlapDecision(JLI, "comicvine:volume:not-in-list")
    state = fixture_state(decisions=(stale,))
    assert evaluate(state)[2].blockers == (Blocker("strict_order", LIST_ID, (M1,)),)
    assert offers(state) == {F1}


def test_multiple_waiting_volumes_preserve_curated_order() -> None:
    """Every approved waiting volume is waived, and the rest keep list order."""
    other_waiting = "comicvine:volume:legion"
    threads = (
        ReadingThread(1, name="JLI", comicvine_volume_id=JLI),
        ReadingThread(2, name="Mister Miracle", comicvine_volume_id=MISTER_MIRACLE),
        ReadingThread(3, name="Legion", comicvine_volume_id=other_waiting),
        ReadingThread(4, name="Outsiders", comicvine_volume_id="comicvine:volume:outsiders"),
    )
    issues = (
        ReadingIssue(1, 1, 1),
        ReadingIssue(2, 1, 2),
        ReadingIssue(3, 2, 1),
        ReadingIssue(4, 3, 1),
        ReadingIssue(5, 4, 1),
    )
    state = ReadingSnapshot(
        user_id=READER_ID,
        threads=threads,
        issues=tuple(
            replace(issue, status="read") if issue.issue_id == 1 else issue
            for issue in issues
        ),
        lists=(
            ReadingList(
                1,
                "strict",
                tuple(ReadingListEntry(i) for i in (1, 3, 4, 5, 2)),
                "JLI",
                (
                    SeriesOverlapDecision(JLI, MISTER_MIRACLE),
                    SeriesOverlapDecision(JLI, other_waiting),
                ),
            ),
        ),
    )
    assert evaluate(state)[1].blockers == (Blocker("strict_order", 1, (5,)),)


def test_overlap_decision_containers_are_immutable_and_validated() -> None:
    """Caller mutation cannot change decisions, and invalid pairs fail closed."""
    decisions = [MISTER_MIRACLE_WAITS]
    reading_list = ReadingList(1, "strict", (), "JLI", decisions)
    decisions.clear()
    assert reading_list.overlap_decisions == (MISTER_MIRACLE_WAITS,)
    with pytest.raises(FrozenInstanceError):
        reading_list.overlap_decisions = ()
    with pytest.raises(ValueError, match="volume identities"):
        SeriesOverlapDecision("", MISTER_MIRACLE)
    with pytest.raises(ValueError, match="volume identities"):
        SeriesOverlapDecision(JLI, "")
    with pytest.raises(ValueError, match="itself"):
        SeriesOverlapDecision(JLI, JLI)
    with pytest.raises(ValueError, match="Duplicate overlap decision"):
        ReadingList(1, "strict", (), "JLI", (MISTER_MIRACLE_WAITS, MISTER_MIRACLE_WAITS))


def test_evaluation_is_deterministic_across_input_permutations() -> None:
    """Decision-aware results do not depend on container order."""
    state = fixture_state()
    expected = evaluate(state)
    for lists in permutations(state.lists):
        for threads in permutations(state.threads):
            for issues in permutations(state.issues):
                assert evaluate(replace(
                    state, lists=lists, threads=threads, issues=issues,
                )) == expected


def test_conversion_projection_preserves_overlap_decisions() -> None:
    """Reviewed list edits must not silently reset the reader's saved choice."""
    snapshot = ReadingSnapshot(
        user_id=READER_ID,
        threads=(
            ReadingThread(1, name="JLI", comicvine_volume_id=JLI),
            ReadingThread(2, name="Mister Miracle", comicvine_volume_id=MISTER_MIRACLE),
        ),
        issues=(
            ReadingIssue(1000, 1, 1, "read"),
            ReadingIssue(1001, 1, 2),
            ReadingIssue(2000, 2, 1),
        ),
        lists=(
            ReadingList(
                5,
                "strict",
                (ReadingListEntry(2000), ReadingListEntry(1001)),
                "JLI",
                (MISTER_MIRACLE_WAITS,),
            ),
        ),
    )
    evidence = ConversionEvidence()
    manifest = build_manifest(
        snapshot,
        evidence,
        ConversionIntent(
            source_fingerprint=snapshot_fingerprint(snapshot, evidence),
            lists=(ListDecision(5, "strict"),),
        ),
    )
    assert manifest.valid is True
    assert manifest.eligibility_before[1] == (1001, True)
    assert manifest.eligibility_after is not None
    assert manifest.eligibility_after[1] == (1001, True)
    assert manifest.eligibility_changes == ()


def test_conversion_fingerprint_includes_overlap_state() -> None:
    """Decision and volume changes invalidate a reviewed conversion intent."""
    base = fixture_state()
    evidence = ConversionEvidence()
    other = SeriesOverlapDecision(JLI, "comicvine:volume:other")
    first = replace(
        base,
        lists=(replace(base.lists[0], overlap_decisions=(MISTER_MIRACLE_WAITS, other)),),
    )
    second = replace(
        base,
        lists=(replace(base.lists[0], overlap_decisions=(other, MISTER_MIRACLE_WAITS)),),
    )
    changed_decision = replace(
        base, lists=(replace(base.lists[0], overlap_decisions=(other,)),),
    )
    changed_volume = replace(
        base,
        threads=tuple(
            replace(thread, comicvine_volume_id="comicvine:volume:renumbered")
            if thread.thread_id == 2
            else thread
            for thread in base.threads
        ),
    )
    assert snapshot_fingerprint(first, evidence) == snapshot_fingerprint(second, evidence)
    assert snapshot_fingerprint(base, evidence) != snapshot_fingerprint(
        changed_decision, evidence
    )
    assert snapshot_fingerprint(base, evidence) != snapshot_fingerprint(
        changed_volume, evidence
    )


def overlap_pair_state(
    *,
    decisions: tuple[SeriesOverlapDecision, ...],
    gate: Literal["none", "hold", "after_previous"] = "none",
    prerequisites: tuple[ReadingPrerequisite, ...] = (),
) -> ReadingSnapshot:
    """Build a strict ``M1, J2`` list with optional gates and prerequisites."""
    return ReadingSnapshot(
        user_id=READER_ID,
        threads=(
            ReadingThread(1, name="JLI", comicvine_volume_id=JLI),
            ReadingThread(2, name="Mister Miracle", comicvine_volume_id=MISTER_MIRACLE),
        ),
        issues=(ReadingIssue(J2, 1, 1), ReadingIssue(M1, 2, 1)),
        lists=(
            ReadingList(
                LIST_ID,
                "strict",
                (ReadingListEntry(M1), ReadingListEntry(J2, gate)),
                "JLI",
                decisions,
            ),
        ),
        prerequisites=prerequisites,
    )


def with_prerequisite(
    state: ReadingSnapshot, prerequisite: ReadingPrerequisite
) -> ReadingSnapshot:
    """Return the snapshot with one extra stored prerequisite."""
    return replace(state, prerequisites=(*state.prerequisites, prerequisite))


def test_validator_accepts_approved_overlap_with_cross_series_prerequisite() -> None:
    """An approved overlap drops the strict edge the evaluator no longer enforces."""
    state = overlap_pair_state(
        decisions=(MISTER_MIRACLE_WAITS,),
        prerequisites=(ReadingPrerequisite(1, J2, M1, "reader"),),
    )
    assert validate_reading_constraints(state) == (J2, M1)


def test_validator_rejects_genuine_cycle_without_the_approved_overlap() -> None:
    """The same graph is a genuine cycle while the approval is missing."""
    state = overlap_pair_state(
        decisions=(),
        prerequisites=(ReadingPrerequisite(1, J2, M1, "reader"),),
    )
    with pytest.raises(ReadingCycleError) as error:
        validate_reading_constraints(state)
    assert [
        (edge.source_issue_id, edge.target_issue_id) for edge in error.value.edges
    ] == [(M1, J2), (J2, M1)]


def test_validator_keeps_explicit_gates_under_an_approved_overlap() -> None:
    """An explicit hold gate is never waived by an approved overlap."""
    state = overlap_pair_state(
        decisions=(MISTER_MIRACLE_WAITS,),
        gate="hold",
        prerequisites=(ReadingPrerequisite(1, J2, M1, "reader"),),
    )
    with pytest.raises(ReadingCycleError) as error:
        validate_reading_constraints(state)
    assert "list JLI hold" in {edge.origin for edge in error.value.edges}


def test_validator_accepts_the_approved_overlap_fixture() -> None:
    """The #1615 graph validates once the reader approved the overlap."""
    assert set(validate_reading_constraints(fixture_state())) == {
        F1, F2, J1, J2, J3, M1, M2,
    }


@pytest.mark.parametrize(("source", "target"), [(M1, J2), (M1, J3), (M2, J3)])
def test_approved_overlap_never_gates_the_waived_pair(source: int, target: int) -> None:
    """A waived pair cannot close a cycle, because the evaluator never gated it."""
    state = with_prerequisite(fixture_state(), ReadingPrerequisite(9, target, source))
    assert set(validate_reading_constraints(state)) == {F1, F2, J1, J2, J3, M1, M2}


@pytest.mark.parametrize(
    ("source", "target"),
    [(J1, J2), (J1, M1), (M1, M2), (J2, M2), (J2, J3)],
)
def test_every_other_strict_pair_still_closes_a_cycle(source: int, target: int) -> None:
    """A pair the evaluator still enforces rejects a contradicting prerequisite."""
    state = with_prerequisite(fixture_state(), ReadingPrerequisite(9, target, source))
    with pytest.raises(ReadingCycleError):
        validate_reading_constraints(state)


def test_conversion_manifest_accepts_an_approved_overlap_graph() -> None:
    """A valid overlap plan is not refused as a reading cycle."""
    state = fixture_state()
    evidence = ConversionEvidence()
    manifest = build_manifest(
        state,
        evidence,
        ConversionIntent(
            source_fingerprint=snapshot_fingerprint(state, evidence),
            lists=(ListDecision(LIST_ID, "strict"),),
        ),
    )
    assert manifest.valid is True
    assert manifest.refusals == ()

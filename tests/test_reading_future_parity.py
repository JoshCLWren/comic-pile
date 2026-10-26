"""A no-op migration must not certify missing future issue handoffs."""

from app.services.reading_future_parity import HistoricalEdge, audit_future_parity
from app.services.reading_list_evaluator import (
    ReadingIssue, ReadingList, ReadingListEntry, ReadingPrerequisite,
    ReadingSnapshot, ReadingThread, evaluate,
)


TEST_READER_ID = 764321

# The production chain from #4198: UXM #360 (read) -> X-Men #80 (unread) ->
# X-Men #1/2 (unread) -> UXM #361 (unread). Dependency 1860 and Thread 305 /
# UXM #361 issue 2029 are the real production identities; the sibling IDs are
# representative fixture identities for the same named series.
UXM_THREAD_ID = 305
XMEN_THREAD_ID = 306
UXM_360_ISSUE_ID = 2028
UXM_361_ISSUE_ID = 2029
XMEN_80_ISSUE_ID = 101874
XMEN_1_2_ISSUE_ID = 101875
LEGACY_UXM_HANDOFF = HistoricalEdge(
    1860, XMEN_1_2_ISSUE_ID, UXM_361_ISSUE_ID, None,
)


def state(
    lists: tuple[ReadingList, ...] = (),
    prerequisites: tuple[ReadingPrerequisite, ...] = (),
    *,
    second_issue: bool = False,
) -> ReadingSnapshot:
    """Create a two-Thread test graph."""
    issues = [ReadingIssue(10, 1, 1), ReadingIssue(20, 2, 1)]
    if second_issue:
        issues.append(ReadingIssue(21, 2, 2))
    return ReadingSnapshot(
        user_id=TEST_READER_ID,
        threads=(ReadingThread(1), ReadingThread(2)),
        issues=tuple(issues),
        lists=lists,
        prerequisites=prerequisites,
    )


def test_unprotected_later_frontier_is_detected() -> None:
    """Missing future handoffs must be reported."""
    old = HistoricalEdge(1000, 10, 21, None)
    report = audit_future_parity(state(second_issue=True), (old,))
    assert not report.safe_to_certify
    assert report.missing == (old,)


def test_reader_prerequisite_is_protected() -> None:
    """Explicit reader prerequisites protect order."""
    old = HistoricalEdge(1000, 10, 20, None)
    live = state(prerequisites=(ReadingPrerequisite(15, 10, 20),))
    assert audit_future_parity(live, (old,)).safe_to_certify


def test_strict_and_loose_are_distinct() -> None:
    """Loose adjacency is not a strict requirement."""
    old = HistoricalEdge(1000, 10, 20, "converted")
    entries = (ReadingListEntry(10), ReadingListEntry(20))
    strict = state(lists=(ReadingList(9, "strict", entries),))
    loose = state(lists=(ReadingList(9, "loose", entries),))
    assert audit_future_parity(strict, (old,)).safe_to_certify
    assert not audit_future_parity(loose, (old,)).safe_to_certify


def test_after_previous_restores_ultimate_handoff() -> None:
    """A gate restores the intended loose-list handoff."""
    old = HistoricalEdge(1000, 10, 20, "converted")
    gated = ReadingList(9, "loose", (
        ReadingListEntry(10), ReadingListEntry(20, "after_previous"),
    ))
    assert audit_future_parity(state(lists=(gated,)), (old,)).safe_to_certify


def test_old_reverse_edge_is_not_silently_accepted() -> None:
    """An old compiler edge cannot invert a strict list."""
    old = HistoricalEdge(1000, 20, 10, "converted")
    strict = ReadingList(9, "strict", (
        ReadingListEntry(10), ReadingListEntry(20),
    ))
    assert not audit_future_parity(state(lists=(strict,)), (old,)).safe_to_certify


def test_excluded_hold_cannot_create_false_order_parity() -> None:
    """An excluded milestone must not prove an order Option E no longer gates."""
    snap = ReadingSnapshot(
        user_id=TEST_READER_ID,
        threads=(ReadingThread(1), ReadingThread(2), ReadingThread(3)),
        issues=(
            ReadingIssue(10, 1, 1),
            ReadingIssue(20, 2, 1),
            ReadingIssue(30, 3, 1),
        ),
        lists=(ReadingList(9, "loose", (
            ReadingListEntry(10), ReadingListEntry(20, "hold"),
            ReadingListEntry(30),
        )),),
        excluded_issue_ids=frozenset({20}),
    )
    old = HistoricalEdge(1010, 10, 30, "converted")
    assert not audit_future_parity(snap, (old,)).safe_to_certify


def test_self_referential_historical_edge_is_unresolved() -> None:
    """A historical edge cannot be implied when it points at its own source."""
    old = HistoricalEdge(1020, 10, 10, None)
    report = audit_future_parity(state(), (old,))
    assert report.missing == (old,)
    assert not report.safe_to_certify


def test_excluded_endpoint_is_reported_not_raised() -> None:
    """Exclude an irrelevant historical relationship without aborting the audit."""
    snap = ReadingSnapshot(
        user_id=TEST_READER_ID,
        threads=(ReadingThread(1), ReadingThread(2)),
        issues=(ReadingIssue(10, 1, 1), ReadingIssue(20, 2, 1)),
        excluded_issue_ids=frozenset({20}),
    )
    old = HistoricalEdge(1010, 10, 20, None)
    report = audit_future_parity(snap, (old,))
    assert report.excluded == (old,)
    assert report.missing == ()
    assert report.examined == 1


def uxm_chain(
    prerequisites: tuple[ReadingPrerequisite, ...] = (),
) -> ReadingSnapshot:
    """Build the #4198 UXM #361 chain with the named production handoff."""
    return ReadingSnapshot(
        user_id=TEST_READER_ID,
        threads=(ReadingThread(UXM_THREAD_ID), ReadingThread(XMEN_THREAD_ID)),
        issues=(
            ReadingIssue(UXM_360_ISSUE_ID, UXM_THREAD_ID, 360, "read"),
            ReadingIssue(UXM_361_ISSUE_ID, UXM_THREAD_ID, 361),
            ReadingIssue(XMEN_80_ISSUE_ID, XMEN_THREAD_ID, 80),
            ReadingIssue(XMEN_1_2_ISSUE_ID, XMEN_THREAD_ID, 81),
        ),
        prerequisites=prerequisites,
    )


def test_named_uxm_handoff_is_reported_before_explicit_correction() -> None:
    """#4198: the unapproved legacy handoff leaves UXM #361 offered prematurely."""
    snap = uxm_chain()
    report = audit_future_parity(snap, (LEGACY_UXM_HANDOFF,))
    assert report.missing == (LEGACY_UXM_HANDOFF,)
    assert not report.safe_to_certify
    assert evaluate(snap)[UXM_THREAD_ID].eligible


def test_named_uxm_handoff_is_protected_by_explicit_prerequisite() -> None:
    """#4198: the authored prerequisite blocks #361 and keeps X-Men #80 eligible."""
    explicit = ReadingPrerequisite(
        1860, XMEN_1_2_ISSUE_ID, UXM_361_ISSUE_ID, "reader",
    )
    snap = uxm_chain((explicit,))
    assert audit_future_parity(snap, (LEGACY_UXM_HANDOFF,)).safe_to_certify
    eligibility = evaluate(snap)
    assert not eligibility[UXM_THREAD_ID].eligible
    assert eligibility[XMEN_THREAD_ID].eligible

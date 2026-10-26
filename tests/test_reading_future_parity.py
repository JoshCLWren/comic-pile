"""A no-op migration must not certify missing future issue handoffs."""

from app.services.reading_future_parity import HistoricalEdge, audit_future_parity
from app.services.reading_list_evaluator import (
    ReadingIssue, ReadingList, ReadingListEntry, ReadingPrerequisite,
    ReadingSnapshot, ReadingThread,
)


TEST_READER_ID = 764321


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

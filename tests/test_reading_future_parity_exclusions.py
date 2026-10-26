"""Excluded issues must not create false future-order parity."""

from app.services.reading_future_parity import HistoricalEdge, audit_future_parity
from app.services.reading_list_evaluator import (
    ReadingIssue, ReadingList, ReadingListEntry, ReadingSnapshot, ReadingThread,
)

TEST_READER_ID = 764322


def example() -> ReadingSnapshot:
    """Create an excluded hold between an unrelated source and target."""
    return ReadingSnapshot(
        user_id=TEST_READER_ID,
        threads=(ReadingThread(1), ReadingThread(2), ReadingThread(3)),
        issues=(
            ReadingIssue(10, 1, 1),
            ReadingIssue(20, 2, 1),
            ReadingIssue(30, 3, 1),
        ),
        lists=(ReadingList(9, "loose", (
            ReadingListEntry(10),
            ReadingListEntry(30, "hold"),
            ReadingListEntry(20),
        )),),
        excluded_issue_ids=frozenset({30}),
    )


def test_excluded_hold_does_not_imply_live_requirement() -> None:
    """Reject phantom A to C ordering through an excluded hold."""
    archived = HistoricalEdge(40, 10, 20, None)
    result = audit_future_parity(example(), (archived,))
    assert result.missing == (archived,)
    assert not result.safe_to_certify


def test_excluded_historical_target_is_reported_not_crashed() -> None:
    """An excluded target is classified as inactive, not a blocking edge."""
    archived = HistoricalEdge(41, 10, 30, "converted")
    result = audit_future_parity(example(), (archived,))
    assert result.missing == ()
    assert result.excluded == (archived,)

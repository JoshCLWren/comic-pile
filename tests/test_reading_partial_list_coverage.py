"""Regression cases for missing unread issues in strict-list Threads."""

from app.services.reading_list_evaluator import (
    ReadingIssue, ReadingList, ReadingListEntry, ReadingSnapshot, ReadingThread,
)
from app.services.reading_partial_list_coverage import partial_strict_coverage


def test_unlisted_future_issue_is_reported():
    """Catch the Authority issue-zero bypass before it becomes a frontier."""
    snap = ReadingSnapshot(
        user_id=1,
        threads=(ReadingThread(1),),
        issues=(ReadingIssue(1, 1, 1), ReadingIssue(2, 1, 2)),
        lists=(ReadingList(10, "strict", (ReadingListEntry(2),)),),
    )
    assert partial_strict_coverage(snap) == ((10, 1),)


def test_independent_loose_and_completed_issues_are_not_gaps():
    """Neither loose list membership nor read issues need strict coverage."""
    snap = ReadingSnapshot(
        user_id=1,
        threads=(ReadingThread(1),),
        issues=(ReadingIssue(1, 1, 1, "read"), ReadingIssue(2, 1, 2)),
        lists=(ReadingList(10, "loose", (ReadingListEntry(1),)),),
    )
    assert partial_strict_coverage(snap) == ()


def test_multiple_strict_lists_each_have_independent_gap():
    """Do not exhaust the unread iterator after the first strict list."""
    snap = ReadingSnapshot(
        user_id=1,
        threads=(ReadingThread(1),),
        issues=(ReadingIssue(1, 1, 1), ReadingIssue(2, 1, 2)),
        lists=(
            ReadingList(10, "strict", (ReadingListEntry(1),)),
            ReadingList(11, "strict", (ReadingListEntry(2),)),
        ),
    )
    assert partial_strict_coverage(snap) == ((10, 2), (11, 1))

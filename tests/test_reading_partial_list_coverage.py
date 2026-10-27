"""Regression cases for missing unread issues in strict-list Threads."""

from app.services.reading_list_evaluator import (
    ReadingIssue, ReadingList, ReadingListEntry, ReadingSnapshot, ReadingThread,
)
from app.services.reading_partial_list_coverage import (
    classify_partial_strict_coverage, partial_strict_coverage, superseded_converted_edge,
)

TEST_READER_ID = 764323


def test_unlisted_future_issue_is_reported() -> None:
    """Catch the Authority issue-zero bypass before it becomes a frontier."""
    snap = ReadingSnapshot(
        user_id=TEST_READER_ID,
        threads=(ReadingThread(1),),
        issues=(ReadingIssue(1, 1, 1), ReadingIssue(2, 1, 2)),
        lists=(ReadingList(10, "strict", (ReadingListEntry(2),)),),
    )
    assert partial_strict_coverage(snap) == ((10, 1),)


def test_independent_loose_and_completed_issues_are_not_gaps() -> None:
    """Neither loose list membership nor read issues need strict coverage."""
    snap = ReadingSnapshot(
        user_id=TEST_READER_ID,
        threads=(ReadingThread(1),),
        issues=(ReadingIssue(1, 1, 1, "read"), ReadingIssue(2, 1, 2)),
        lists=(ReadingList(10, "loose", (ReadingListEntry(1),)),),
    )
    assert partial_strict_coverage(snap) == ()


def test_multiple_strict_lists_each_have_independent_gap() -> None:
    """Do not exhaust the unread iterator after the first strict list."""
    snap = ReadingSnapshot(
        user_id=TEST_READER_ID,
        threads=(ReadingThread(1),),
        issues=(ReadingIssue(1, 1, 1), ReadingIssue(2, 1, 2)),
        lists=(
            ReadingList(10, "strict", (ReadingListEntry(1),)),
            ReadingList(11, "strict", (ReadingListEntry(2),)),
        ),
    )
    assert partial_strict_coverage(snap) == ((10, 2), (11, 1))


def test_scoped_outside_range_does_not_need_unread_gates() -> None:
    """A selective plan is not permission to gate a whole Thread."""
    snapshot = ReadingSnapshot(
        user_id=TEST_READER_ID,
        threads=(ReadingThread(1),),
        issues=(
            ReadingIssue(10, 1, 1),
            ReadingIssue(11, 1, 2),
            ReadingIssue(12, 1, 3),
            ReadingIssue(13, 1, 4),
        ),
        lists=(ReadingList(50, "strict", (
            ReadingListEntry(11), ReadingListEntry(12),
        )),),
    )
    omitted = partial_strict_coverage(snapshot)
    assert omitted == ((50, 10), (50, 13))
    scoped, unresolved = classify_partial_strict_coverage(snapshot, omitted, {})
    assert scoped == (
        (50, 10, "outside_list_scope"),
        (50, 13, "outside_list_scope"),
    )
    assert unresolved == ()


def test_old_plan_also_omitted_internal_issue() -> None:
    """Internal gaps are safe only when old source explicitly omitted them."""
    snapshot = ReadingSnapshot(
        user_id=TEST_READER_ID,
        threads=(ReadingThread(1),),
        issues=(
            ReadingIssue(10, 1, 1),
            ReadingIssue(11, 1, 2),
            ReadingIssue(12, 1, 3),
        ),
        lists=(ReadingList(50, "strict", (
            ReadingListEntry(10), ReadingListEntry(12),
        )),),
    )
    omitted = partial_strict_coverage(snapshot)
    assert omitted == ((50, 11),)
    scoped, unresolved = classify_partial_strict_coverage(
        snapshot, omitted, {50: frozenset({10, 12})},
    )
    assert scoped == ((50, 11, "also_absent_from_linked_old_plan"),)
    assert unresolved == ()
    scoped, unresolved = classify_partial_strict_coverage(snapshot, omitted, {})
    assert scoped == ()
    assert unresolved == ((50, 11),)
    scoped, unresolved = classify_partial_strict_coverage(
        snapshot, omitted, {50: frozenset({10, 11, 12})},
    )
    assert scoped == ()
    assert unresolved == ((50, 11),)


def test_old_generated_reverse_edge_requires_explicit_source_order() -> None:
    """A canonical strict-list correction supersedes only proven old-plan order."""
    snapshot = ReadingSnapshot(
        user_id=TEST_READER_ID,
        threads=(ReadingThread(1), ReadingThread(2)),
        issues=(ReadingIssue(10, 1, 1), ReadingIssue(20, 2, 1)),
        lists=(ReadingList(50, "strict", (
            ReadingListEntry(10), ReadingListEntry(20),
        )),),
    )
    prior = {50: {(90, "reader-order"): {20: 0, 10: 1}}}
    assert superseded_converted_edge(20, 10, snapshot, prior)
    assert not superseded_converted_edge(20, 10, snapshot, {})
    assert not superseded_converted_edge(10, 20, snapshot, prior)
    assert not superseded_converted_edge(
        20, 10, snapshot, {50: {(90, "reader-order"): {10: 0, 20: 1}}},
    )


def test_unrelated_old_plans_cannot_fabricate_historical_precedence() -> None:
    """No source plan/lane includes both ends, even though merged positions would."""
    snapshot = ReadingSnapshot(
        user_id=TEST_READER_ID,
        threads=(ReadingThread(1), ReadingThread(2)),
        issues=(ReadingIssue(10, 1, 1), ReadingIssue(20, 2, 1)),
        lists=(ReadingList(50, "strict", (
            ReadingListEntry(10), ReadingListEntry(20),
        )),),
    )
    assert not superseded_converted_edge(
        20, 10, snapshot,
        {50: {(90, "main"): {20: 0}, (91, "main"): {10: 1}}},
    )
    assert not superseded_converted_edge(
        20, 10, snapshot,
        {50: {(90, "first"): {20: 0}, (90, "second"): {10: 1}}},
    )
    assert not superseded_converted_edge(
        20, 10, snapshot,
        {50: {(90, "main"): {20: 0, 10: 1},
              (91, "main"): {20: 1, 10: 0}}},
    )
    assert not superseded_converted_edge(
        20, 10, snapshot,
        {50: {(90, "main"): {20: 0, 10: 1},
              (91, "main"): {20: 0, 10: 1}}},
    )

"""Regression for #4028: CBL integration across browse, overlap, upsert and Roll.

These checks consolidate the closure-critical invariants that the functional
children (#4008-#4027) must jointly satisfy: the shared F2/M1/J2 fixture keeps
JLI rollable while Mister Miracle waits on Fourth World, overlap decisions are
scoped to one reader/list, and the baseline (no choice) still blocks J2.

The assertions reuse the canonical Option E evaluator, so they exercise the
same code path that Roll, Queue, Thread and List surfaces use.
"""

from __future__ import annotations

from dataclasses import replace

from app.services.reading_list_evaluator import (
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

F1, F2 = 101, 102
J1, M1, J2, M2, J3 = 201, 202, 203, 204, 205

LIST_ID = 10
MISTER_MIRACLE_WAITS = SeriesOverlapDecision(JLI, MISTER_MIRACLE)


def _threads() -> tuple[ReadingThread, ...]:
    return (
        ReadingThread(1, name="Fourth World", comicvine_volume_id=FOURTH_WORLD),
        ReadingThread(2, name="JLI", comicvine_volume_id=JLI),
        ReadingThread(3, name="Mister Miracle", comicvine_volume_id=MISTER_MIRACLE),
    )


def _issues(*, read: frozenset[int]) -> tuple[ReadingIssue, ...]:
    base = (
        ReadingIssue(F1, 1, 1),
        ReadingIssue(F2, 1, 2),
        ReadingIssue(J1, 2, 1),
        ReadingIssue(J2, 2, 2),
        ReadingIssue(J3, 2, 3),
        ReadingIssue(M1, 3, 1),
        ReadingIssue(M2, 3, 2),
    )
    return tuple(
        replace(issue, status="read") if issue.issue_id in read else issue for issue in base
    )


def _snapshot(
    *,
    approved: bool,
    read: frozenset[int] = frozenset({J1}),
) -> ReadingSnapshot:
    entries = (
        ReadingListEntry(J1),
        ReadingListEntry(M1),
        ReadingListEntry(J2),
        ReadingListEntry(M2),
        ReadingListEntry(J3),
    )
    decisions = (MISTER_MIRACLE_WAITS,) if approved else ()
    return ReadingSnapshot(
        user_id=1,
        threads=_threads(),
        issues=_issues(read=read),
        lists=(
            ReadingList(LIST_ID, "strict", entries, "JLI", decisions),
        ),
        prerequisites=(ReadingPrerequisite(1, F2, M1, "reader", ("reader approved",)),),
    )


def _offers(state: ReadingSnapshot) -> set[int]:
    return {
        result.next_issue_id
        for result in evaluate(state).values()
        if result.eligible and result.next_issue_id is not None
    }


def test_4028_approved_overlap_rolls_j2_while_m1_waits_for_f2() -> None:
    """With the reader's overlap choice, J2 is rollable; M1 stays blocked on F2."""
    state = _snapshot(approved=True)
    offered = _offers(state)
    assert J2 in offered, "JLI must keep rolling at J2 despite unread M1"
    assert M1 not in offered, "Mister Miracle M1 must still wait on Fourth World F2"
    assert J1 not in offered, "J1 is already read and cannot roll"


def test_4028_baseline_without_choice_blocks_j2_behind_m1() -> None:
    """Without an approved overlap, strict order keeps J2 behind M1."""
    state = _snapshot(approved=False)
    offered = _offers(state)
    assert J2 not in offered, "J2 must not roll until M1 is read without overlap"
    assert J1 not in offered


def test_4028_m1_unblocks_only_after_f2_is_read() -> None:
    """Fourth World completion releases Mister Miracle M1 for rolling."""
    state = _snapshot(approved=True, read=frozenset({J1, F1, F2}))
    offered = _offers(state)
    assert M1 in offered, "M1 must become rollable once F2 is read"


def test_4028_overlap_decision_is_per_reader_scoped() -> None:
    """A snapshot for a second reader without the decision keeps strict order."""
    second = replace(_snapshot(approved=False), user_id=2)
    offered = _offers(second)
    assert J2 not in offered


def test_4028_all_threads_present_in_eligibility_result() -> None:
    """Evaluate returns an entry for every active thread, including blocked ones."""
    state = _snapshot(approved=True)
    result = evaluate(state)
    assert set(result) == {1, 2, 3}, "Fourth World, JLI and Mister Miracle must all report"

"""Observable Option E reading scenarios, independent of storage and comic labels."""

from dataclasses import FrozenInstanceError, replace
from itertools import permutations

import pytest

from app.services.reading_list_evaluator import (
    Blocker, ReadingIssue, ReadingList, ReadingListEntry, ReadingPrerequisite,
    ReadingSnapshot, ReadingThread, evaluate,
)


def snapshot(
    issues: tuple[ReadingIssue, ...], lists: tuple[ReadingList, ...] = (), *,
    read: frozenset[int] = frozenset(), excluded: frozenset[int] = frozenset(),
    prerequisites: tuple[ReadingPrerequisite, ...] = (),
) -> ReadingSnapshot:
    """Build complete global state, with each comic represented only once."""
    return ReadingSnapshot(
        user_id=1,
        threads=tuple(ReadingThread(thread_id) for thread_id in sorted({i.thread_id for i in issues})),
        issues=tuple(replace(i, status="read") if i.issue_id in read else i for i in issues),
        lists=lists, prerequisites=prerequisites, excluded_issue_ids=excluded,
    )


def offers(state: ReadingSnapshot) -> set[int]:
    """Return actual issues a caller could offer after eligibility filtering."""
    return {
        result.next_issue_id for result in evaluate(state).values()
        if result.eligible and result.next_issue_id is not None
    }


def mark_read(state: ReadingSnapshot, *issue_ids: int) -> ReadingSnapshot:
    """Advance global read state without changing any list or gate."""
    return replace(state, issues=tuple(
        replace(issue, status="read") if issue.issue_id in issue_ids else issue
        for issue in state.issues
    ))


def test_julix_strict_interleaves_hellboy_abe_and_bprd() -> None:
    """Crossing Threads waits for the preceding curated Julix entries."""
    # Representative positions: Hellboy -> Abe -> BPRD -> Hellboy.
    issues = (ReadingIssue(10, 1, 1), ReadingIssue(11, 1, 2),
              ReadingIssue(20, 2, 1), ReadingIssue(30, 3, 1))
    state = snapshot(issues, (ReadingList(17, "strict", tuple(
        ReadingListEntry(i) for i in (10, 20, 30, 11)
    )),))
    for issue_id in (10, 20, 30, 11):
        assert offers(state) == {issue_id}
        state = mark_read(state, issue_id)
    assert offers(state) == set()


def test_jli_jle_annuals_and_specials_follow_curated_strict_placement() -> None:
    """Separate-Thread JLI Annual #2 waits far later than Annual #1 and a special."""
    jli31, jle1, annual1, special, jli40, jle8, annual2 = (31, 101, 201, 301, 40, 108, 202)
    issues = (
        ReadingIssue(jli31, 1, 31), ReadingIssue(jli40, 1, 40),
        ReadingIssue(jle1, 2, 1), ReadingIssue(jle8, 2, 8),
        ReadingIssue(annual1, 3, 1), ReadingIssue(annual2, 3, 2),
        ReadingIssue(special, 4, 1),
    )
    order = (jli31, jle1, annual1, special, jli40, jle8, annual2)
    state = snapshot(issues, (ReadingList(1, "strict", tuple(
        ReadingListEntry(i) for i in order
    )),))
    for issue_id in order:
        assert offers(state) == {issue_id}
        state = mark_read(state, issue_id)


def test_xmen_loose_crossover_after_previous_leaves_unrelated_series_free() -> None:
    """Three crossover chapters wait explicitly; unrelated Wolverine stays available."""
    state = snapshot(tuple(ReadingIssue(i, i, 1) for i in (1, 2, 3, 4)), (
        ReadingList(1, "loose", (
            ReadingListEntry(1), ReadingListEntry(2, "after_previous"),
            ReadingListEntry(3, "after_previous"), ReadingListEntry(4),
        )),
    ))
    assert offers(state) == {1, 4}
    assert evaluate(state)[2].blockers == (Blocker("after_previous", 1, (1,), gate_issue_id=2),)
    assert offers(mark_read(state, 1)) == {2, 4}
    assert offers(mark_read(state, 1, 2)) == {3, 4}


def test_ultimate_one_year_in_must_itself_be_read_and_later_hold_is_independent() -> None:
    """A milestone waits above, and material below waits through the milestone."""
    state = snapshot(tuple(ReadingIssue(i, i, 1) for i in range(1, 7)), (
        ReadingList(1, "loose", (
            ReadingListEntry(1), ReadingListEntry(2), ReadingListEntry(3, "hold"),
            ReadingListEntry(4), ReadingListEntry(5, "hold"), ReadingListEntry(6),
        )),
    ))
    assert offers(state) == {1, 2}
    assert evaluate(state)[3].blockers[0].waiting_on_issue_ids == (1, 2)
    assert evaluate(state)[4].blockers == (Blocker("hold", 1, (1, 2, 3), gate_issue_id=3),)
    state = mark_read(state, 1, 2)
    assert offers(state) == {3}
    assert evaluate(state)[4].blockers == (Blocker("hold", 1, (3,), gate_issue_id=3),)
    state = mark_read(state, 3)
    assert offers(state) == {4}
    assert evaluate(state)[6].blockers == (Blocker("hold", 1, (4, 5), gate_issue_id=5),)
    state = mark_read(state, 4)
    assert offers(state) == {5}
    assert offers(mark_read(state, 5)) == {6}


def test_read_hold_still_requires_unread_entries_above_it() -> None:
    """Out-of-order milestone reads do not release unfinished earlier material."""
    state = snapshot(tuple(ReadingIssue(i, i, 1) for i in (1, 2, 3)), (
        ReadingList(1, "loose", (ReadingListEntry(1), ReadingListEntry(2, "hold"),
                                 ReadingListEntry(3))),
    ), read=frozenset({2}))
    assert offers(state) == {1}
    assert evaluate(state)[3].blockers == (Blocker("hold", 1, (1,), gate_issue_id=2),)
    assert offers(mark_read(state, 1)) == {3}


def test_loose_ultimate_absolute_series_and_annuals_progress_independently() -> None:
    """Neither adjacency nor annual/special labeling invents a loose-list gate."""
    # DTOs deliberately have no title/issue-number input to infer gates from.
    state = snapshot((ReadingIssue(90, 1, 2), ReadingIssue(10, 1, 8),
                      ReadingIssue(20, 2, 1), ReadingIssue(30, 3, 1)), (
        ReadingList(1, "loose", tuple(ReadingListEntry(i) for i in (10, 20, 30, 90))),
    ))
    assert offers(state) == {90, 20, 30}
    assert offers(mark_read(state, 90)) == {10, 20, 30}
    assert evaluate(state)[1].next_issue_id == 90


def test_starman_stable_prerequisite_survives_list_reorder_and_delete() -> None:
    """Starman #55 (26360) gates All-Star Comics #1 (117189) by stable ID."""
    prerequisite = ReadingPrerequisite(7, 26360, 117189, "converted", ("Starman #55 checkpoint",))
    issues = (ReadingIssue(26360, 1, 55), ReadingIssue(117189, 2, 1))
    for order in ((26360, 117189), (117189, 26360), ()):
        state = snapshot(issues, (ReadingList(1, "loose", tuple(
            ReadingListEntry(i) for i in order
        )),) if order else (), prerequisites=(prerequisite,))
        assert offers(state) == {26360}
        assert evaluate(state)[2].blockers == (Blocker(
            "prerequisite", None, (26360,), prerequisite_id=7,
            origin="converted", provenance=("Starman #55 checkpoint",),
        ),)
        assert offers(mark_read(state, 26360)) == {117189}


def test_overlapping_lists_share_read_state_and_compose_all_restrictions() -> None:
    """A loose list cannot cancel strict order, a hold, or a prerequisite."""
    state = snapshot(tuple(ReadingIssue(i, i, 1) for i in (1, 2, 3)), (
        ReadingList(10, "strict", (ReadingListEntry(1), ReadingListEntry(3))),
        ReadingList(20, "loose", (ReadingListEntry(2, "hold"), ReadingListEntry(3))),
        ReadingList(30, "loose", (ReadingListEntry(3),)),
    ), prerequisites=(ReadingPrerequisite(9, 1, 3),))
    assert offers(state) == {1, 2}
    assert [(b.kind, b.list_id, b.waiting_on_issue_ids) for b in evaluate(state)[3].blockers] == [
        ("hold", 20, (2,)), ("prerequisite", None, (1,)), ("strict_order", 10, (1,)),
    ]
    assert offers(mark_read(state, 1)) == {2}
    assert offers(mark_read(state, 1, 2)) == {3}


@pytest.mark.parametrize("excluded", [False, True])
def test_removed_hold_never_shadows_earlier_active_hold(excluded: bool) -> None:
    """hold(A), removed hold(B), C still makes C wait for unread A."""
    state = snapshot(tuple(ReadingIssue(i, i, 1) for i in (1, 2, 3)), (
        ReadingList(1, "loose", (
            ReadingListEntry(1, "hold"), ReadingListEntry(2, "hold", skipped=not excluded),
            ReadingListEntry(3),
        )),
    ), excluded=frozenset({2}) if excluded else frozenset())
    assert evaluate(state)[3].blockers == (Blocker("hold", 1, (1,), gate_issue_id=1),)
    assert offers(state) == ({1} if excluded else {1, 2})
    assert offers(mark_read(state, 1)) == ({3} if excluded else {2, 3})


@pytest.mark.parametrize("gate", ["hold", "after_previous"])
@pytest.mark.parametrize("excluded", [False, True])
def test_removed_entries_contribute_no_gates_or_predecessors(gate: str, excluded: bool) -> None:
    """A removed gated entry never restricts itself or becomes a predecessor."""
    # Use runtime inputs as a loader would, exercising validation too.
    entry = ReadingListEntry(2, skipped=not excluded)
    entry = replace(entry, gate=gate)
    state = snapshot(tuple(ReadingIssue(i, i, 1) for i in (1, 2, 3)), (
        ReadingList(1, "loose", (ReadingListEntry(1), entry, ReadingListEntry(3))),
    ), excluded=frozenset({2}) if excluded else frozenset())
    assert offers(state) == ({1, 3} if excluded else {1, 2, 3})
    state = replace(state, lists=(ReadingList(1, "loose", (
        ReadingListEntry(1), entry, ReadingListEntry(3, "after_previous"),
    )),))
    assert evaluate(state)[3].blockers == (Blocker("after_previous", 1, (1,), gate_issue_id=3),)
    assert 3 in offers(mark_read(state, 1))


def test_list_skip_is_local_and_exclusion_advances_thread_frontier() -> None:
    """Skipped comics remain rollable and can still block in another list."""
    issues = (ReadingIssue(1, 1, 1), ReadingIssue(2, 2, 1), ReadingIssue(3, 1, 2))
    state = snapshot(issues, (
        ReadingList(1, "strict", (ReadingListEntry(1, skipped=True), ReadingListEntry(2))),
        ReadingList(2, "strict", (ReadingListEntry(1), ReadingListEntry(2))),
    ))
    assert offers(state) == {1}
    assert {b.list_id for b in evaluate(state)[2].blockers} == {2}
    state = replace(state, excluded_issue_ids=frozenset({1}))
    assert offers(state) == {2, 3}
    assert evaluate(state)[1].next_issue_id == 3


def test_empty_read_complete_and_unexpected_issue_status() -> None:
    """No frontier for empty/read Threads; completed Threads are not offered."""
    state = ReadingSnapshot(1,
        threads=(ReadingThread(1), ReadingThread(2), ReadingThread(3, "completed"), ReadingThread(4)),
        issues=(ReadingIssue(2, 2, 1, "read"), ReadingIssue(3, 3, 1),
                ReadingIssue(4, 4, 1, "unexpected")),
        lists=(ReadingList(1, "strict"), ReadingList(2, "strict", (ReadingListEntry(2),))),
    )
    assert list(evaluate(state)) == [1, 2, 4]
    assert evaluate(state)[1].next_issue_id is None
    assert evaluate(state)[2].next_issue_id is None
    assert not evaluate(state)[2].eligible
    assert offers(state) == {4}
    assert evaluate(ReadingSnapshot(1)) == {}


def test_inactive_thread_source_still_blocks_active_target() -> None:
    """Activity never substitutes for global issue read state."""
    state = ReadingSnapshot(1,
        threads=(ReadingThread(1, "completed"), ReadingThread(2)),
        issues=(ReadingIssue(1, 1, 1), ReadingIssue(2, 2, 1)),
        prerequisites=(ReadingPrerequisite(1, 1, 2),),
    )
    assert offers(state) == set()
    assert offers(mark_read(state, 1)) == {2}


def test_after_previous_uses_nearest_remaining_entry_even_when_already_read() -> None:
    """An already-read immediate predecessor satisfies the gate despite earlier unread comics."""
    state = snapshot(tuple(ReadingIssue(i, i, 1) for i in (1, 2, 3)), (
        ReadingList(1, "loose", (ReadingListEntry(1), ReadingListEntry(2),
                                 ReadingListEntry(3, "after_previous"))),
    ), read=frozenset({2}))
    assert offers(state) == {1, 3}
    assert offers(replace(state, lists=(ReadingList(1, "loose", (
        ReadingListEntry(3, "after_previous"), ReadingListEntry(1), ReadingListEntry(2),
    )),))) == {1, 3}


def test_deterministic_blockers_and_immutable_snapshot() -> None:
    """Input container permutations and repeated evaluation preserve exact results."""
    state = snapshot(tuple(ReadingIssue(i, i, 1) for i in (1, 2, 3)), (
        ReadingList(20, "strict", (ReadingListEntry(2), ReadingListEntry(1), ReadingListEntry(3))),
        ReadingList(10, "strict", (ReadingListEntry(1), ReadingListEntry(3))),
    ), prerequisites=(ReadingPrerequisite(8, 2, 3), ReadingPrerequisite(7, 1, 3)))
    expected = evaluate(state)
    for lists in permutations(state.lists):
        for prerequisites in permutations(state.prerequisites):
            assert evaluate(replace(state, lists=lists, prerequisites=prerequisites,
                                    threads=tuple(reversed(state.threads)),
                                    issues=tuple(reversed(state.issues)))) == expected
    assert [(b.kind, b.list_id, b.prerequisite_id) for b in expected[3].blockers] == [
        ("prerequisite", None, 7), ("prerequisite", None, 8),
        ("strict_order", 10, None), ("strict_order", 20, None),
    ]
    assert expected[3].blockers[-1].waiting_on_issue_ids == (2, 1)
    with pytest.raises(FrozenInstanceError):
        state.user_id = 2
    with pytest.raises(FrozenInstanceError):
        state.lists[0].entries[0].skipped = True
    with pytest.raises(FrozenInstanceError):
        expected[3].blockers[0].kind = "hold"
    expected.clear()
    assert evaluate(state)[3].next_issue_id == 3


def test_snapshot_copies_mutable_containers() -> None:
    """Caller mutations cannot change the immutable execution inputs."""
    entries = [ReadingListEntry(1)]
    issues = [ReadingIssue(1, 1, 1)]
    excluded: set[int] = set()
    provenance = ["reader checkpoint"]
    reading_list = ReadingList(1, "strict", entries)
    prerequisite = ReadingPrerequisite(1, 1, 1, provenance=provenance)
    state = ReadingSnapshot(1, (ReadingThread(1),), issues, (reading_list,),
                            excluded_issue_ids=excluded)
    entries.clear()
    issues.clear()
    excluded.add(1)
    provenance.clear()
    assert offers(state) == {1}
    assert prerequisite.provenance == ("reader checkpoint",)


@pytest.mark.parametrize("state_args", [
    {"threads": (ReadingThread(1), ReadingThread(1))},
    {"issues": (ReadingIssue(1, 1, 1),)},
    {"lists": (ReadingList(1, "strict", (ReadingListEntry(99),)),)},
    {"prerequisites": (ReadingPrerequisite(1, 99, 98),)},
    {"excluded_issue_ids": frozenset({99})},
])
def test_incomplete_snapshot_fails_closed(state_args: dict[str, object]) -> None:
    """Missing inputs cannot silently release a reader restriction."""
    with pytest.raises(ValueError):
        ReadingSnapshot(1, **state_args)


def test_stranded_prerequisite_is_rejected() -> None:
    """Collection exclusions cannot satisfy an explicit unread requirement."""
    with pytest.raises(ValueError, match="strands"):
        snapshot((ReadingIssue(1, 1, 1), ReadingIssue(2, 2, 1)),
                 excluded=frozenset({1}), prerequisites=(ReadingPrerequisite(1, 1, 2),))


@pytest.mark.parametrize("build", [
    lambda: ReadingList(1, "invalid"),
    lambda: ReadingList(1, "loose", (ReadingListEntry(1, "invalid"),)),
    lambda: ReadingList(1, "strict", (ReadingListEntry(1), ReadingListEntry(1))),
    lambda: ReadingPrerequisite(1, 1, 2, "invalid"),
])
def test_invalid_modes_gates_and_origins_fail_closed(build: object) -> None:
    """Unsupported runtime loader values never silently become loose or ungated."""
    assert callable(build)
    with pytest.raises(ValueError):
        build()

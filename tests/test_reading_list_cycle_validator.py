"""Combined Option E constraint validation regressions."""

import pytest

from app.services.reading_list_cycle_validator import (
    ReadingCycleError,
    validate_reading_constraints,
)
from app.services.reading_list_evaluator import (
    ReadingIssue,
    ReadingList,
    ReadingListEntry,
    ReadingPrerequisite,
    ReadingSnapshot,
    ReadingThread,
)


def snapshot(
    lists: tuple[ReadingList, ...] = (),
    prerequisites: tuple[ReadingPrerequisite, ...] = (),
    *,
    read: bool = False,
    excluded: frozenset[int] = frozenset(),
) -> ReadingSnapshot:
    """Build three independent Issues with one shared global state."""
    return ReadingSnapshot(
        1,
        tuple(ReadingThread(i, name=f"Hero {i}") for i in (1, 2, 3)),
        tuple(ReadingIssue(i, i, 1, "read" if read else "unread") for i in (1, 2, 3)),
        lists,
        prerequisites,
        excluded,
    )


def test_three_lists_form_indirect_cycle_even_when_read() -> None:
    """Three list edges must be combined rather than checked pairwise."""
    lists = (
        ReadingList(10, "strict", (ReadingListEntry(1), ReadingListEntry(2))),
        ReadingList(20, "strict", (ReadingListEntry(2), ReadingListEntry(3))),
        ReadingList(30, "strict", (ReadingListEntry(3), ReadingListEntry(1))),
    )
    with pytest.raises(ReadingCycleError) as error:
        validate_reading_constraints(
            snapshot(lists, read=True), list_names={10: "Alpha", 20: "Beta", 30: "Gamma"}
        )
    assert [
        (edge.source_issue_id, edge.target_issue_id, edge.origin) for edge in error.value.edges
    ] == [
        (1, 2, "list Alpha strict order"),
        (2, 3, "list Beta strict order"),
        (3, 1, "list Gamma strict order"),
    ]
    assert "Issue 1" in str(error.value)


def test_cycle_spans_series_hold_and_prerequisite() -> None:
    """Natural series position, milestone and stable edge share one graph."""
    state = ReadingSnapshot(
        1,
        (ReadingThread(7, name="Hero"), ReadingThread(8, name="Event Thread")),
        (ReadingIssue(1, 7, 1), ReadingIssue(2, 7, 2), ReadingIssue(3, 8, 1)),
        (ReadingList(10, "loose", (ReadingListEntry(2), ReadingListEntry(3, "hold"))),),
        (ReadingPrerequisite(99, 3, 1),),
    )
    with pytest.raises(ReadingCycleError) as error:
        validate_reading_constraints(state, list_names={10: "Event"}, thread_names={7: "Hero"})
    assert [
        (edge.source_issue_id, edge.target_issue_id, edge.origin) for edge in error.value.edges
    ] == [
        (1, 2, "Thread Hero series order"),
        (2, 3, "list Event hold"),
        (3, 1, "prerequisite 99 (reader)"),
    ]


def test_hold_milestone_blocks_later_entries_in_combined_graph() -> None:
    """A later placement cannot precede an unread hold milestone."""
    state = snapshot(
        (ReadingList(10, "loose", (ReadingListEntry(1, "hold"), ReadingListEntry(2))),),
        (ReadingPrerequisite(9, 2, 1),),
    )
    with pytest.raises(ReadingCycleError) as error:
        validate_reading_constraints(state, list_names={10: "One Year In"})
    assert [(edge.source_issue_id, edge.target_issue_id) for edge in error.value.edges] == [
        (1, 2),
        (2, 1),
    ]
    assert "list One Year In hold" in str(error.value)


def test_earlier_hold_still_blocks_below_a_later_hold() -> None:
    """The first milestone remains a direct constraint below the second."""
    state = ReadingSnapshot(
        1,
        tuple(ReadingThread(i, name=f"Hero {i}") for i in range(1, 5)),
        tuple(ReadingIssue(i, i, 1, "unread" if i == 2 else "read") for i in range(1, 5)),
        (
            ReadingList(
                10,
                "loose",
                (
                    ReadingListEntry(1),
                    ReadingListEntry(2, "hold"),
                    ReadingListEntry(3, "hold"),
                    ReadingListEntry(4),
                ),
                name="Milestones",
            ),
        ),
        (ReadingPrerequisite(1, 4, 2),),
    )
    with pytest.raises(ReadingCycleError) as error:
        validate_reading_constraints(state)
    assert [
        (edge.source_issue_id, edge.target_issue_id, edge.origin) for edge in error.value.edges
    ] == [
        (2, 3, "list Milestones hold"),
        (3, 4, "list Milestones hold"),
        (4, 2, "prerequisite 1 (reader)"),
    ]


def test_default_call_uses_snapshot_names_in_cycle_diagnostic() -> None:
    """Callers can get named origins without separate diagnostic maps."""
    state = ReadingSnapshot(
        1,
        (ReadingThread(1, name="Hero"), ReadingThread(2, name="Villain")),
        (ReadingIssue(1, 1, 1), ReadingIssue(2, 1, 2), ReadingIssue(3, 2, 1)),
        (
            ReadingList(
                10, "loose", (ReadingListEntry(2), ReadingListEntry(3, "hold")), name="Event"
            ),
        ),
        (ReadingPrerequisite(1, 3, 1),),
    )
    with pytest.raises(ReadingCycleError) as error:
        validate_reading_constraints(state)
    assert "Thread Hero series order" in str(error.value)
    assert "list Event hold" in str(error.value)


def test_unnamed_acyclic_snapshot_validates() -> None:
    """Diagnostic labels are optional when validating stored constraints."""
    state = ReadingSnapshot(
        1,
        (ReadingThread(7),),
        (ReadingIssue(1, 7, 1), ReadingIssue(2, 7, 2)),
        (ReadingList(10, "strict", (ReadingListEntry(1), ReadingListEntry(2))),),
    )
    assert validate_reading_constraints(state) == (1, 2)


def test_unnamed_cycle_uses_stable_id_labels() -> None:
    """Cycle diagnostics identify unnamed Threads and lists by stable IDs."""
    state = ReadingSnapshot(
        1,
        (ReadingThread(7),),
        (ReadingIssue(1, 7, 1), ReadingIssue(2, 7, 2)),
        (ReadingList(10, "strict", (ReadingListEntry(2), ReadingListEntry(1))),),
    )
    with pytest.raises(ReadingCycleError) as error:
        validate_reading_constraints(state)
    assert "Thread #7 series order" in str(error.value)
    assert "list #10 strict order" in str(error.value)


def test_excluded_prerequisite_source_fails_closed() -> None:
    """An exclusion cannot silently drop an explicit requirement."""
    with pytest.raises(ValueError, match="strands an explicit prerequisite"):
        snapshot(prerequisites=(ReadingPrerequisite(1, 1, 2),), excluded=frozenset({1}))


def test_stable_topological_order_and_positional_gates() -> None:
    """An acyclic graph returns deterministic order independent of input order."""
    entries = (
        ReadingListEntry(1),
        ReadingListEntry(2, "after_previous"),
        ReadingListEntry(3, "hold"),
    )
    state = snapshot((ReadingList(10, "loose", entries, name="Event"),))
    assert validate_reading_constraints(state) == (1, 2, 3)
    assert validate_reading_constraints(state) == validate_reading_constraints(state)


def test_input_order_does_not_change_topological_result() -> None:
    """The helper uses graph structure and Issue IDs, not snapshot container order."""
    state = snapshot(
        (
            ReadingList(
                10,
                "loose",
                (ReadingListEntry(1), ReadingListEntry(2, "after_previous")),
                name="Event",
            ),
        )
    )
    reversed_state = ReadingSnapshot(
        state.user_id,
        state.threads[::-1],
        state.issues[::-1],
        state.lists,
        state.prerequisites,
        state.excluded_issue_ids,
    )
    assert validate_reading_constraints(state) == validate_reading_constraints(reversed_state)


def test_long_cycle_uses_bounded_iterative_walk() -> None:
    """A long strict list closes through a prerequisite without recursive DFS."""
    issue_count = 1200
    state = ReadingSnapshot(
        1,
        tuple(
            ReadingThread(issue_id, name=f"Hero {issue_id}")
            for issue_id in range(1, issue_count + 1)
        ),
        tuple(ReadingIssue(issue_id, issue_id, 1) for issue_id in range(1, issue_count + 1)),
        (
            ReadingList(
                1,
                "strict",
                tuple(ReadingListEntry(issue_id) for issue_id in range(1, issue_count + 1)),
                name="Long Event",
            ),
        ),
        (ReadingPrerequisite(1, issue_count, 1),),
    )
    with pytest.raises(ReadingCycleError) as error:
        validate_reading_constraints(state)
    assert len(error.value.edges) == issue_count
    assert error.value.edges[-1].target_issue_id == 1


def test_exclusion_removes_series_position_but_not_remaining_order() -> None:
    """Stored series order is validated even across a collection exclusion."""
    state = ReadingSnapshot(
        1,
        (ReadingThread(1, name="Hero"),),
        (ReadingIssue(1, 1, 1), ReadingIssue(2, 1, 2), ReadingIssue(3, 1, 3)),
        (),
        (),
        frozenset({2}),
    )
    with pytest.raises(ReadingCycleError) as error:
        validate_reading_constraints(
            ReadingSnapshot(
                state.user_id,
                state.threads,
                state.issues,
                state.lists,
                (ReadingPrerequisite(1, 3, 1),),
                state.excluded_issue_ids,
            ),
        )
    assert [(edge.source_issue_id, edge.target_issue_id) for edge in error.value.edges] == [
        (1, 2),
        (2, 3),
        (3, 1),
    ]


def test_after_previous_cycle_and_local_skip() -> None:
    """A loose gate participates in cycles, while a skipped placement does not."""
    gated = ReadingList(
        10, "loose", (ReadingListEntry(1), ReadingListEntry(2, "after_previous")), name="Event"
    )
    prerequisite = ReadingPrerequisite(1, 2, 1)
    with pytest.raises(ReadingCycleError, match="after_previous"):
        validate_reading_constraints(snapshot((gated,), (prerequisite,)))

    skipped = ReadingList(
        10,
        "loose",
        (ReadingListEntry(1, skipped=True), ReadingListEntry(2, "after_previous")),
        name="Event",
    )
    assert validate_reading_constraints(snapshot((skipped,), (prerequisite,))) == (2, 1, 3)


def test_strict_order_survives_excluded_middle_entry() -> None:
    """A prerequisite cannot reverse strict A -> C through excluded B."""
    state = snapshot(
        (ReadingList(10, "strict", tuple(ReadingListEntry(i) for i in (1, 2, 3)), name="Event"),),
        (ReadingPrerequisite(1, 3, 1),),
        excluded=frozenset({2}),
    )
    with pytest.raises(ReadingCycleError) as error:
        validate_reading_constraints(state)
    assert error.value.edges[-1].origin == "prerequisite 1 (reader)"
    assert "list Event strict order" in str(error.value)


def test_exclusion_cannot_conceal_cycle_through_excluded_entry() -> None:
    """Stored list cycles remain invalid when one member is globally excluded."""
    state = snapshot(
        (
            ReadingList(10, "strict", (ReadingListEntry(1), ReadingListEntry(2)), name="First"),
            ReadingList(20, "strict", (ReadingListEntry(2), ReadingListEntry(1)), name="Second"),
        ),
        excluded=frozenset({2}),
    )
    with pytest.raises(ReadingCycleError) as error:
        validate_reading_constraints(state)
    assert {edge.origin for edge in error.value.edges} == {
        "list First strict order", "list Second strict order"
    }


def test_long_strict_list_with_many_holds_has_linear_edges() -> None:
    """Thousands of milestones validate without a dense prefix graph."""
    issue_count = 4000
    state = ReadingSnapshot(
        1,
        tuple(ReadingThread(i, name=f"Hero {i}") for i in range(1, issue_count + 1)),
        tuple(ReadingIssue(i, i, 1) for i in range(1, issue_count + 1)),
        (
            ReadingList(
                1,
                "strict",
                tuple(ReadingListEntry(i, "hold" if i % 2 == 0 else "none")
                      for i in range(1, issue_count + 1)),
                name="Long Event",
            ),
        ),
    )
    assert validate_reading_constraints(state) == tuple(range(1, issue_count + 1))


def test_cycle_search_passes_residual_dead_end() -> None:
    """A residual node can lead to a terminal branch before the actual cycle."""
    state = snapshot(
        prerequisites=(
            ReadingPrerequisite(1, 1, 2),
            ReadingPrerequisite(2, 1, 3),
            ReadingPrerequisite(3, 3, 2),
            ReadingPrerequisite(4, 3, 1),
        ),
    )
    with pytest.raises(ReadingCycleError) as error:
        validate_reading_constraints(state)
    assert [(edge.source_issue_id, edge.target_issue_id) for edge in error.value.edges] == [
        (1, 3),
        (3, 1),
    ]

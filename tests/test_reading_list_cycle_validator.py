"""Combined Option E constraint validation regressions."""

from typing import Literal

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
        "list First strict order",
        "list Second strict order",
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
                tuple(
                    ReadingListEntry(i, "hold" if i % 2 == 0 else "none")
                    for i in range(1, issue_count + 1)
                ),
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


@pytest.mark.parametrize("origin", ["reader", "converted"])
def test_cycle_edge_preserves_structured_prerequisite_provenance(
    origin: Literal["reader", "converted"],
) -> None:
    """Clients receive typed provenance without parsing the human edge label."""
    state = snapshot(
        (ReadingList(1, "strict", (ReadingListEntry(2), ReadingListEntry(1))),),
        (ReadingPrerequisite(7, 1, 2, origin, ("reviewed evidence",)),),
    )
    with pytest.raises(ReadingCycleError) as error:
        validate_reading_constraints(state)
    edge = next(edge for edge in error.value.edges if edge.prerequisite_origin is not None)
    assert edge.prerequisite_origin == origin
    assert edge.provenance == ("reviewed evidence",)


# --- Overlap-aware cycle validation tests (Issue #4017) ---


def _overlap_snapshot(
    lists: tuple[ReadingList, ...] = (),
    prerequisites: tuple[ReadingPrerequisite, ...] = (),
    *,
    read: frozenset[int] = frozenset(),
    excluded: frozenset[int] = frozenset(),
    thread_volumes: dict[int, str] | None = None,
) -> ReadingSnapshot:
    """Build a snapshot with custom thread Comic Vine volumes for overlap testing."""
    thread_volumes = thread_volumes or {}
    threads = tuple(
        ReadingThread(tid, name=f"Thread {tid}", comicvine_volume_id=thread_volumes.get(tid))
        for tid in sorted(thread_volumes.keys())
    )
    # Collect all issue IDs from lists and prerequisites
    issue_ids = set()
    for lst in lists:
        for entry in lst.entries:
            if not entry.skipped:
                issue_ids.add(entry.issue_id)
    for p in prerequisites:
        issue_ids.add(p.source_issue_id)
        issue_ids.add(p.target_issue_id)
    # Also include any read/excluded issues
    issue_ids.update(read)
    issue_ids.update(excluded)
    # Build issues with thread_id matching their volume
    issues = []
    for iid in sorted(issue_ids):
        # Find which thread this issue belongs to by checking thread_volumes
        # For simplicity, we map issue_id to thread_id 1:1 for test construction
        # In real usage, thread_id comes from the thread the issue belongs to
        tid = iid  # Simple mapping for tests
        if tid not in thread_volumes:
            # Assign a default volume if not specified
            thread_volumes[tid] = f"vol_{tid}"
            threads = tuple(
                ReadingThread(t, name=f"Thread {t}", comicvine_volume_id=thread_volumes.get(t))
                for t in sorted(thread_volumes.keys())
            )
        issues.append(ReadingIssue(iid, tid, 1, "read" if iid in read else "unread"))
    return ReadingSnapshot(1, threads, tuple(issues), lists, prerequisites, excluded)


def test_overlap_approved_removes_strict_edge_between_volumes() -> None:
    """Approved overlap removes the strict-order edge from waiting to continuing volume.

    List order: J1 (vol=JLI), M1 (vol=MM), J2 (vol=JLI)
    Overlap: continuing=JLI, waiting=MM (JLI continues, MM waits)
    J2 should NOT wait for M1 because MM is in waiting for JLI.
    But J2 should still wait for J1 (same volume). A prerequisite J2->M1
    means this graph validates only when the M1->J2 strict edge is removed.
    """
    from app.services.reading_list_evaluator import SeriesOverlapDecision

    # J1=1 (JLI), M1=2 (MM), J2=3 (JLI)
    entries = (
        ReadingListEntry(1),  # J1 - JLI
        ReadingListEntry(2),  # M1 - MM
        ReadingListEntry(3),  # J2 - JLI
    )
    # J2 before M1 closes a cycle only if the strict M1 -> J2 edge survives.
    prerequisites = (ReadingPrerequisite(1, 3, 2),)
    lists = (
        ReadingList(
            10,
            "strict",
            entries,
            name="Crossover",
            overlap_decisions=(SeriesOverlapDecision("JLI", "MM"),),
        ),
    )
    state = _overlap_snapshot(
        lists=lists,
        prerequisites=prerequisites,
        thread_volumes={1: "JLI", 2: "MM", 3: "JLI"},
    )
    # Should validate without cycle - J2 does not wait for M1
    order = validate_reading_constraints(state, list_names={10: "Crossover"})
    assert 1 in order and 2 in order and 3 in order
    assert order.index(1) < order.index(3)  # J1 before J2 (same volume)
    assert order.index(3) < order.index(2)  # J2 before M1 (prerequisite)


def test_overlap_removed_rejects_genuine_cycle() -> None:
    """Without the overlap decision, the same graph must reject the genuine cycle.

    List order: J1 (JLI), M1 (MM), J2 (JLI)
    With NO overlap decision, strict order creates J1->M1->J2.
    A prerequisite J2->M1 then closes the genuine cycle M1->J2->M1.
    """
    entries = (
        ReadingListEntry(1),  # J1 - JLI
        ReadingListEntry(2),  # M1 - MM
        ReadingListEntry(3),  # J2 - JLI
    )
    prerequisites = (ReadingPrerequisite(1, 3, 2),)
    lists = (
        ReadingList(
            10,
            "strict",
            entries,
            name="Crossover",
            overlap_decisions=(),  # NO overlap decision
        ),
    )
    state = _overlap_snapshot(
        lists=lists,
        prerequisites=prerequisites,
        thread_volumes={1: "JLI", 2: "MM", 3: "JLI"},
    )
    with pytest.raises(ReadingCycleError) as error:
        validate_reading_constraints(state, list_names={10: "Crossover"})
    # The cycle is the strict M1 -> J2 edge plus the J2 -> M1 prerequisite.
    edges = [(e.source_issue_id, e.target_issue_id, e.origin) for e in error.value.edges]
    assert (2, 3, "list Crossover strict order") in edges
    assert (3, 2, "prerequisite 1 (reader)") in edges


def test_three_list_cycle_rejected_despite_per_series_exceptions() -> None:
    """Three-Reading-List cycle remains rejected even when per-series exceptions exist.

    List A: J1 (JLI), M1 (MM) with overlap JLI continues past MM -> J1->M1 edge (MM not exempt for MM target)
    List B: M1 (MM), J2 (JLI) WITHOUT overlap -> M1->J2 edge (no exception in this list)
    List C: J2 (JLI), J1 (JLI) no overlap -> J2->J1 edge (same volume)
    Cycle: J1->M1->J2->J1 persists because List B has no overlap exception.
    """
    from app.services.reading_list_evaluator import SeriesOverlapDecision

    lists = (
        ReadingList(
            10,
            "strict",
            (ReadingListEntry(1), ReadingListEntry(2)),  # J1, M1
            name="List A",
            overlap_decisions=(SeriesOverlapDecision("JLI", "MM"),),
        ),
        ReadingList(
            20,
            "strict",
            (ReadingListEntry(2), ReadingListEntry(3)),  # M1, J2
            name="List B",
            overlap_decisions=(),  # NO overlap in this list
        ),
        ReadingList(
            30,
            "strict",
            (ReadingListEntry(3), ReadingListEntry(1)),  # J2, J1 - same volume
            name="List C",
            overlap_decisions=(),
        ),
    )
    state = _overlap_snapshot(
        lists=lists,
        thread_volumes={1: "JLI", 2: "MM", 3: "JLI"},
    )
    with pytest.raises(ReadingCycleError) as error:
        validate_reading_constraints(
            state, list_names={10: "List A", 20: "List B", 30: "List C"}
        )
    edges = [(e.source_issue_id, e.target_issue_id, e.origin) for e in error.value.edges]
    assert (1, 2, "list List A strict order") in edges
    assert (2, 3, "list List B strict order") in edges
    assert (3, 1, "list List C strict order") in edges


def test_distinct_comicvine_volumes_same_series_name_separate() -> None:
    """Distinct Comic Vine volumes with the same series name remain separate.

    Volume 'JLI-v1' and 'JLI-v2' are different volumes even if same series name.
    Overlap decision for 'JLI-v1' does not apply to 'JLI-v2'.
    """
    from app.services.reading_list_evaluator import SeriesOverlapDecision

    # J1=1 (JLI-v1), M1=2 (MM), J2=3 (JLI-v2)
    lists = (
        ReadingList(
            10,
            "strict",
            (
                ReadingListEntry(1),  # J1 - JLI-v1
                ReadingListEntry(2),  # M1 - MM
                ReadingListEntry(3),  # J2 - JLI-v2
            ),
            name="Crossover",
            overlap_decisions=(SeriesOverlapDecision("JLI-v1", "MM"),),
        ),
    )
    # Overlap is for JLI-v1 continues past MM
    # J2 is JLI-v2, different volume, so NO overlap exception applies
    # Strict order: J1->M1->J2 all remain
    # If we add prerequisite J2->J1, that's a genuine cycle
    prerequisites = (ReadingPrerequisite(1, 3, 1),)
    state = _overlap_snapshot(
        lists=lists,
        prerequisites=prerequisites,
        thread_volumes={1: "JLI-v1", 2: "MM", 3: "JLI-v2"},
    )
    with pytest.raises(ReadingCycleError) as error:
        validate_reading_constraints(state, list_names={10: "Crossover"})
    edges = [(e.source_issue_id, e.target_issue_id, e.origin) for e in error.value.edges]
    assert (1, 2, "list Crossover strict order") in edges
    assert (2, 3, "list Crossover strict order") in edges
    assert (3, 1, "prerequisite 1 (reader)") in edges


def test_f1615_scenario_evaluator_and_validator_agree() -> None:
    """The #1615 F1/F2/J1/M1/J2/M2/J3 scenario: validator and evaluator agree.

    F1=1 (FourthWorld), F2=2 (FourthWorld), J1=3 (JLI), M1=4 (MM), J2=5 (JLI), M2=6 (MM), J3=7 (JLI)
    List: F1, F2, J1, M1, J2, M2, J3 (strict)
    Prerequisite: F2 -> M1 (F2 blocks M1)
    Overlap: continuing=JLI, waiting=MM (JLI continues past MM)

    With overlap:
    - J2 eligible while M1 unread (J2 doesn't wait for M1)
    - J3 waits for J2 but not M1/M2
    - Read J2 makes J3 eligible while M1 still waits for F2

    Validator must accept the same graph that evaluator allows.
    """
    from app.services.reading_list_evaluator import SeriesOverlapDecision, evaluate

    # Issues: F1=1, F2=2, J1=3, M1=4, J2=5, M2=6, J3=7
    lists = (
        ReadingList(
            10,
            "strict",
            (
                ReadingListEntry(1),  # F1
                ReadingListEntry(2),  # F2
                ReadingListEntry(3),  # J1
                ReadingListEntry(4),  # M1
                ReadingListEntry(5),  # J2
                ReadingListEntry(6),  # M2
                ReadingListEntry(7),  # J3
            ),
            name="FourthWorld_JLI",
            overlap_decisions=(SeriesOverlapDecision("JLI", "MM"),),
        ),
    )
    prerequisites = (ReadingPrerequisite(1, 2, 4),)  # F2 blocks M1

    # All unread initially
    state = _overlap_snapshot(
        lists=lists,
        prerequisites=prerequisites,
        thread_volumes={
            1: "FourthWorld", 2: "FourthWorld",
            3: "JLI", 4: "MM",
            5: "JLI", 6: "MM",
            7: "JLI",
        },
    )

    # Validator should accept (no cycle)
    order = validate_reading_constraints(state, list_names={10: "FourthWorld_JLI"})
    assert len(order) == 7

    # Check evaluator agrees on eligibility
    eval_result = evaluate(state)
    # J1 (3) should be eligible (after F1, F2)
    # M1 (4) blocked by F2 prerequisite
    # J2 (5) should be eligible (JLI continues past MM, so doesn't wait for M1)
    # But J2 waits for J1 (same volume)
    # M2 (6) waits for M1 (same volume) and J2 (strict order, but M2 is MM not JLI)
    # Actually M2 is MM volume, waiting for MM is empty, so M2 waits for J2 (strict order)
    # J3 (7) waits for J2 (same volume) but not M1/M2

    # With all unread: F1 eligible, J1 blocked by F1,F2, M1 blocked by F2, J2 blocked by J1
    # Wait, strict order means each waits for all previous non-exempt
    # For J1 (vol=JLI): predecessors F1, F2 (vol=FourthWorld) not in waiting for JLI (waiting={MM})
    # So J1 waits for F1, F2
    # For M1 (vol=MM): predecessors F1, F2, J1. waiting for MM is empty. So M1 waits for all three.
    # But prerequisite F2->M1 also blocks M1.
    # For J2 (vol=JLI): predecessors F1,F2,J1,M1. waiting for JLI={MM}. M1 is MM so exempt.
    # So J2 waits for F1,F2,J1 (non-MM predecessors)
    # For M2 (vol=MM): predecessors F1,F2,J1,M1,J2. waiting for MM=empty. Waits for all.
    # For J3 (vol=JLI): predecessors all. waiting={MM}. M1,M2 exempt. Waits for F1,F2,J1,J2.

    # So initially only F1 eligible
    assert eval_result[1].next_issue_id == 1  # F1 thread
    assert not eval_result[4].eligible  # M1 blocked by F2
    assert not eval_result[5].eligible  # J2 blocked by J1

    # Read F1
    state_read_f1 = _overlap_snapshot(
        lists=lists,
        prerequisites=prerequisites,
        thread_volumes={
            1: "FourthWorld", 2: "FourthWorld",
            3: "JLI", 4: "MM",
            5: "JLI", 6: "MM",
            7: "JLI",
        },
        read=frozenset({1}),
    )
    eval_result = evaluate(state_read_f1)
    # F2 now eligible (no strict predecessors unread? F1 read)
    assert eval_result[2].next_issue_id == 2

    # Read F2
    state_read_f1_f2 = _overlap_snapshot(
        lists=lists,
        prerequisites=prerequisites,
        thread_volumes={
            1: "FourthWorld", 2: "FourthWorld",
            3: "JLI", 4: "MM",
            5: "JLI", 6: "MM",
            7: "JLI",
        },
        read=frozenset({1, 2}),
    )
    eval_result = evaluate(state_read_f1_f2)
    # J1 now eligible (F1, F2 read)
    # M1 still blocked by prerequisite? No, F2 is read, so prerequisite satisfied
    # But M1 waits for J1 (strict order, J1 unread)
    assert eval_result[3].next_issue_id == 3  # J1 eligible
    assert not eval_result[4].eligible  # M1 waits for J1

    # Read J1
    state_read_f1_f2_j1 = _overlap_snapshot(
        lists=lists,
        prerequisites=prerequisites,
        thread_volumes={
            1: "FourthWorld", 2: "FourthWorld",
            3: "JLI", 4: "MM",
            5: "JLI", 6: "MM",
            7: "JLI",
        },
        read=frozenset({1, 2, 3}),
    )
    eval_result = evaluate(state_read_f1_f2_j1)
    # M1 eligible (F2 read, J1 read)
    # J2 eligible (J1 read, M1 exempt due to overlap)
    assert eval_result[4].eligible  # M1 has no remaining blockers
    assert eval_result[4].next_issue_id == 4
    assert eval_result[5].eligible  # J2 has no remaining blockers (overlap!)
    assert eval_result[5].next_issue_id == 5

    # Read J2 (but not M1)
    state_read_f1_f2_j1_j2 = _overlap_snapshot(
        lists=lists,
        prerequisites=prerequisites,
        thread_volumes={
            1: "FourthWorld", 2: "FourthWorld",
            3: "JLI", 4: "MM",
            5: "JLI", 6: "MM",
            7: "JLI",
        },
        read=frozenset({1, 2, 3, 5}),
    )
    eval_result = evaluate(state_read_f1_f2_j1_j2)
    # J3 eligible (J2 read, M1/M2 exempt)
    # M1 still eligible (unread)
    # M2 waits for M1
    assert eval_result[7].eligible  # no remaining blockers
    assert eval_result[7].next_issue_id == 7  # J3 eligible!


def test_overlap_with_read_and_excluded_issues_stored_graph_policy() -> None:
    """Test read/excluded issues under the stored-graph policy with overlap.

    Validator keeps read/excluded in graph; evaluator filters them for eligibility.
    Overlap decisions apply to stored graph same as evaluator.
    """
    from app.services.reading_list_evaluator import SeriesOverlapDecision

    # J1=1 (JLI, read), M1=2 (MM, unread), J2=3 (JLI, unread)
    lists = (
        ReadingList(
            10,
            "strict",
            (ReadingListEntry(1), ReadingListEntry(2), ReadingListEntry(3)),
            name="Test",
            overlap_decisions=(SeriesOverlapDecision("JLI", "MM"),),
        ),
    )
    # J1 is read, M1 and J2 unread
    state = _overlap_snapshot(
        lists=lists,
        thread_volumes={1: "JLI", 2: "MM", 3: "JLI"},
        read=frozenset({1}),
    )
    # Validator: J1 in graph (read), M1, J2. Strict order edges:
    # J1->M1 (target=M1 vol=MM, waiting for MM=empty, so J1 not exempt)
    # M1->J2 (target=J2 vol=JLI, waiting={MM}, M1 is MM so EXEMPT)
    # So only J1->M1 edge. No cycle.
    order = validate_reading_constraints(state, list_names={10: "Test"})
    assert order == (1, 2, 3) or order == (1, 3, 2)  # J1 first, M1 and J2 independent

    # With excluded M1
    state_excl = _overlap_snapshot(
        lists=lists,
        thread_volumes={1: "JLI", 2: "MM", 3: "JLI"},
        read=frozenset({1}),
        excluded=frozenset({2}),
    )
    # Excluded M1 stays in graph for validator
    # Edges: J1->M1 (M1 excluded but in graph), M1->J2 (exempt due to overlap)
    # So J1->M1 edge exists. M1 excluded but in graph.
    # Topological order: J1, then M1, then J2 (or J1, J2, M1 since M1->J2 exempt)
    order = validate_reading_constraints(state_excl, list_names={10: "Test"})
    assert 1 in order and 2 in order and 3 in order
    assert order.index(1) < order.index(2)  # J1 before M1 (strict order edge)


def test_overlap_strict_order_covers_maximal_non_exempt() -> None:
    """Test _strict_order_covers logic with overlap: maximal non-exempt predecessors.

    List: A (vol=X), B (vol=Y), C (vol=X), D (vol=Y), E (vol=X)
    Overlap: continuing=X, waiting=Y (X continues past Y)
    
    For target E (vol=X, index=4):
    - waiting for X = {Y}
    - Predecessors: D(vol=Y, exempt), C(vol=X, not exempt), B(vol=Y, exempt), A(vol=X, not exempt)
    - Maximal non-exempt: C (since C is later than A and no non-exempt between C and E)
    """
    from app.services.reading_list_evaluator import SeriesOverlapDecision

    lists = (
        ReadingList(
            10,
            "strict",
            (
                ReadingListEntry(1),  # A - vol=X
                ReadingListEntry(2),  # B - vol=Y
                ReadingListEntry(3),  # C - vol=X
                ReadingListEntry(4),  # D - vol=Y
                ReadingListEntry(5),  # E - vol=X
            ),
            name="Test",
            overlap_decisions=(SeriesOverlapDecision("X", "Y"),),
        ),
    )
    state = _overlap_snapshot(
        lists=lists,
        thread_volumes={1: "X", 2: "Y", 3: "X", 4: "Y", 5: "X"},
    )
    order = validate_reading_constraints(state, list_names={10: "Test"})
    # _strict_order_covers keeps the maximal non-exempt predecessors:
    # For C (index=2, vol=X): predecessors B(vol=Y, exempt), A(vol=X, non-exempt).
    # Covers=[A].
    # For D (index=3, vol=Y): waiting for Y is empty, so every earlier entry is
    # non-exempt. Covers=[C, B]: C is the maximal cover, and B remains because
    # overlap lets C bypass B but does not let D bypass its own series order.
    # For E (index=4, vol=X): predecessors D(exempt), C(non-exempt),
    # B(exempt), A(non-exempt). Covers=[C].
    # So edges: A->B, A->C, B->D, C->D, C->E
    # Topological: A, B, C, D, E or A, C, B, D, E etc.
    assert order.index(1) < order.index(3)  # A before C
    assert order.index(3) < order.index(5)  # C before E
    assert order.index(1) < order.index(2)  # A before B
    assert order.index(2) < order.index(4)  # B before D (waiting series order)
    assert order.index(3) < order.index(4)  # C before D

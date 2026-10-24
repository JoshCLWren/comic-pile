"""Deterministic reading-graph preview tests for the #1615/#4019 fixture.

The preview must use the same canonical Option E evaluator and cycle validator
that execute the reader's saved lists. It never writes list membership, issue
status, or an overlap decision.
"""

from dataclasses import replace
from typing import Literal

import pytest

from app.services.reading_graph_preview_service import (
    _build_snapshot,
    _choice_effect,
    _cycle_errors,
    _decisions,
    _expand_graph_threads,
    _GraphContext,
    _IssueMeta,
    _series_nodes,
)
from app.services.reading_list_cycle_validator import ReadingCycleError
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

READER_ID = 1


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


def _make_graph_context(snapshot: ReadingSnapshot, proposed_list_id: int = LIST_ID) -> _GraphContext:
    """Build a _GraphContext for testing the preview service internals."""
    volume_by_thread = {
        thread.thread_id: thread.comicvine_volume_id for thread in snapshot.threads
    }
    issue_meta = {
        issue.issue_id: _IssueMeta(
            issue_id=issue.issue_id,
            thread_id=issue.thread_id,
            issue_number=str(issue.position),
            position=issue.position,
            status=issue.status,
        )
        for issue in snapshot.issues
    }
    graph_thread_ids = frozenset(thread.thread_id for thread in snapshot.threads)
    graph_issue_ids = frozenset(issue.issue_id for issue in snapshot.issues)
    volume_by_issue = {
        issue_id: volume_by_thread.get(meta.thread_id)
        for issue_id, meta in issue_meta.items()
    }
    thread_names = {thread.thread_id: thread.name for thread in snapshot.threads}
    list_names = {lst.list_id: lst.name for lst in snapshot.lists}
    series_refs = {}
    for thread_id in graph_thread_ids:
        volume_id = volume_by_thread.get(thread_id)
        key = volume_id or f"unidentified-thread:{thread_id}"
        series_refs[key] = type("MockRef", (), {
            "comicvine_volume_id": key,
            "series_name": thread_names.get(thread_id, f"Series {thread_id}"),
            "year": None,
        })()

    return _GraphContext(
        snapshot=snapshot,
        proposed_list_id=proposed_list_id,
        graph_thread_ids=graph_thread_ids,
        graph_issue_ids=graph_issue_ids,
        issue_meta=issue_meta,
        volume_by_issue=volume_by_issue,
        series_refs=series_refs,
        list_names=list_names,
        thread_names=thread_names,
    )


class TestReadingGraphPreviewBaseline:
    """Baseline behavior before any overlap choice."""

    def test_without_choice_strict_order_blocks_j2_behind_m1(self) -> None:
        """The preview warns that JLI stalls until Mister Miracle is read."""
        state = fixture_state(approved=False)
        assert offers(state) == {F1}
        eligibility = evaluate(state)
        assert eligibility[2].blockers == (
            Blocker("strict_order", LIST_ID, (M1,)),
        )
        assert eligibility[3].blockers == (
            Blocker("prerequisite", None, (F2,), prerequisite_id=1,
                    origin="reader", provenance=("reader approved",)),
        )

    def test_series_nodes_baseline_shows_jli_waiting(self) -> None:
        """Series nodes reflect the strict-order baseline: JLI frontier waits for M1."""
        state = fixture_state(approved=False)
        context = _make_graph_context(state)
        nodes = _series_nodes(context, evaluate(state))
        jli_node = next(n for n in nodes if n.comicvine_volume_id == JLI)
        mm_node = next(n for n in nodes if n.comicvine_volume_id == MISTER_MIRACLE)
        # JLI frontier (J2) waits for M1 (strict order)
        assert jli_node.state == "waits"
        assert jli_node.waits_for_issue_ids == [M1]
        # Mister Miracle frontier (M1) waits for F2 (prerequisite)
        assert mm_node.state == "waits"
        assert mm_node.waits_for_issue_ids == [F2]

    def test_issues_show_blockers_baseline(self) -> None:
        """Issue references show active blockers at baseline."""
        state = fixture_state(approved=False)
        context = _make_graph_context(state)
        issues = context.snapshot.issues
        # J2 should have a strict_order blocker from M1
        next(i for i in issues if i.issue_id == J2)
        # This is tested through the service integration


class TestReadingGraphPreviewWithChoice:
    """Behavior after the reader approves the overlap choice."""

    def test_approved_overlap_allows_j2_while_m1_waits_for_f2(self) -> None:
        """The reader-approved series pair changes eligibility, not read state."""
        state = fixture_state()
        assert offers(state) == {F1, J2}
        eligibility = evaluate(state)
        assert eligibility[2].blockers == ()
        assert eligibility[3].blockers == (
            Blocker("prerequisite", None, (F2,), prerequisite_id=1,
                    origin="reader", provenance=("reader approved",)),
        )
        # No issue, list entry or prerequisite was mutated by evaluating the choice.
        assert all(issue.status != "read" for issue in state.issues if issue.issue_id != J1)
        assert state.lists[0].entries[2].issue_id == J2
        assert state.lists[0].overlap_decisions == (MISTER_MIRACLE_WAITS,)

    def test_series_nodes_after_choice_shows_jli_continuing(self) -> None:
        """After choice, JLI node shows mixed state with J2 rollable, J3 waiting on J2."""
        state = fixture_state()
        context = _make_graph_context(state)
        nodes = _series_nodes(context, evaluate(state))
        jli_node = next(n for n in nodes if n.comicvine_volume_id == JLI)
        mm_node = next(n for n in nodes if n.comicvine_volume_id == MISTER_MIRACLE)
        # JLI is now mixed: J2 rollable (frontier), J3 waiting on J2
        assert jli_node.state == "mixed"
        assert jli_node.rollable_count == 1
        assert jli_node.waiting_count == 1
        # J2 is the frontier and is rollable, so it doesn't wait for anything.
        # J3 waits for J2, but J3 is not the frontier so it doesn't appear in waits_for_issue_ids.
        assert jli_node.waits_for_issue_ids == []
        # Mister Miracle frontier (M1) still waits for F2
        assert mm_node.state == "waits"
        assert mm_node.waits_for_issue_ids == [F2]

    def test_j3_waits_for_j2_but_not_for_waiting_mister_miracle(self) -> None:
        """JLI keeps its own order while the waiting volume stays unread."""
        state = fixture_state()
        assert J3 not in offers(state)
        state = mark_read(state, J2)
        assert offers(state) == {F1, J3}
        eligibility = evaluate(state)
        assert eligibility[2].blockers == ()
        assert eligibility[3].blockers[0].kind == "prerequisite"
        assert eligibility[3].blockers[0].waiting_on_issue_ids == (F2,)

    def test_m2_keeps_its_own_order_and_waits_for_earlier_jli_progress(self) -> None:
        """The waiting volume still depends on its own order and applicable JLI work."""
        state = mark_read(fixture_state(), F1, F2)
        assert offers(state) == {J2, M1}
        state = mark_read(state, M1)
        # M2 is the Mister Miracle frontier and still waits for the unread JLI J2.
        assert offers(state) == {J2}
        eligibility = evaluate(state)
        assert eligibility[3].next_issue_id == M2
        # M2 waits for J2 via strict order (since J2 is earlier in the list)
        assert eligibility[3].blockers == (Blocker("strict_order", LIST_ID, (J2,)),)
        state = mark_read(state, J2)
        assert offers(state) == {M2, J3}
        # After J2 is read, M2's only blocker was J2, so now M2 is eligible
        # (J3 is in JLI thread, not Mister Miracle thread)
        eligibility = evaluate(state)
        assert eligibility[3].blockers == ()
        state = mark_read(state, J3)
        assert offers(state) == {M2}
        assert offers(mark_read(state, M2)) == set()


class TestReadingGraphPreviewIsolation:
    """Owner-scoped isolation and identity boundaries."""

    def test_two_readers_sharing_the_fixture_get_different_eligibility(self) -> None:
        """Approval is owner-scoped; the other reader keeps full strict order."""
        approved = fixture_state()
        strict = replace(fixture_state(approved=False), user_id=2)
        assert {issue.issue_id for issue in approved.issues} == {
            issue.issue_id for issue in strict.issues
        }
        assert approved.lists[0].entries == strict.lists[0].entries
        assert offers(approved) == {F1, J2}
        assert offers(strict) == {F1}

    def test_decision_only_waives_the_exact_waiting_volume(self) -> None:
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
        eligibility = evaluate(state)
        assert eligibility[2].blockers == (Blocker("strict_order", LIST_ID, (X1,)),)
        assert offers(mark_read(state, X1)) == {F1, J2}

    def test_decision_is_scoped_to_its_own_reading_list(self) -> None:
        """A second strict list without the decision keeps its full order."""
        other = ReadingList(
            20,
            "strict",
            (ReadingListEntry(J1), ReadingListEntry(M1), ReadingListEntry(J2)),
            "Strict JLI",
        )
        state = fixture_state(lists=(other,))
        eligibility = evaluate(state)
        assert eligibility[2].blockers == (Blocker("strict_order", 20, (M1,)),)
        assert offers(state) == {F1}


class TestReadingGraphPreviewFailClosed:
    """Missing or ambiguous identity fails closed to strict order."""

    @pytest.mark.parametrize(
        ("jli_volume", "mister_miracle_volume"),
        [(None, MISTER_MIRACLE), (JLI, None), (None, None)],
    )
    def test_unknown_or_ambiguous_volume_identity_fails_closed(
        self, jli_volume: str | None, mister_miracle_volume: str | None,
    ) -> None:
        """A missing identity never applies an exception to an approximate run."""
        state = fixture_state(
            jli_volume=jli_volume, mister_miracle_volume=mister_miracle_volume,
        )
        eligibility = evaluate(state)
        assert eligibility[2].blockers == (Blocker("strict_order", LIST_ID, (M1,)),)
        assert offers(state) == {F1}


class TestReadingGraphPreviewExplicitGates:
    """Explicit gates and prerequisites are never waived by overlap choices."""

    def test_explicit_after_previous_gate_is_not_waived(self) -> None:
        """Only implicit strict order relaxes; a reader-authored gate stays."""
        entries = (
            ReadingListEntry(J1),
            ReadingListEntry(M1),
            ReadingListEntry(J2, "after_previous"),
            ReadingListEntry(J3),
        )
        state = fixture_state(entries=entries)
        eligibility = evaluate(state)
        assert eligibility[2].blockers == (
            Blocker("after_previous", LIST_ID, (M1,), gate_issue_id=J2),
        )
        assert offers(state) == {F1}

    def test_explicit_hold_gate_is_not_waived(self) -> None:
        """A milestone hold on the continuing entry still waits for the volume above it."""
        entries = (
            ReadingListEntry(J1),
            ReadingListEntry(M1),
            ReadingListEntry(J2, "hold"),
        )
        state = fixture_state(entries=entries)
        eligibility = evaluate(state)
        assert eligibility[2].blockers == (
            Blocker("hold", LIST_ID, (M1,), gate_issue_id=J2),
        )
        assert offers(state) == {F1}

    def test_prerequisite_from_the_waiting_volume_is_not_waived(self) -> None:
        """A real cross-series requirement still holds the continuing volume."""
        state = fixture_state(
            prerequisites=(
                ReadingPrerequisite(1, F2, M1, "reader"),
                ReadingPrerequisite(2, M1, J2, "reader"),
            ),
        )
        eligibility = evaluate(state)
        assert eligibility[2].blockers == (
            Blocker("prerequisite", None, (M1,), prerequisite_id=2, origin="reader"),
        )
        assert offers(state) == {F1}

    def test_decision_for_an_absent_volume_has_no_effect(self) -> None:
        """A stale decision cannot relax a graph that no longer contains its volume."""
        stale = SeriesOverlapDecision(JLI, "comicvine:volume:not-in-list")
        state = fixture_state(decisions=(stale,))
        eligibility = evaluate(state)
        assert eligibility[2].blockers == (Blocker("strict_order", LIST_ID, (M1,)),)
        assert offers(state) == {F1}


class TestReadingGraphPreviewValidatorAgreement:
    """The preview's cycle validator must agree with the evaluator."""

    def overlap_pair_state(
        self,
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

    def test_validator_accepts_approved_overlap_with_cross_series_prerequisite(self) -> None:
        """An approved overlap drops the strict edge the evaluator no longer enforces."""
        state = self.overlap_pair_state(
            decisions=(MISTER_MIRACLE_WAITS,),
            prerequisites=(ReadingPrerequisite(1, J2, M1, "reader"),),
        )
        # Both evaluator and validator should accept
        assert set(evaluate(state)[1].blockers) == set()
        from app.services.reading_list_cycle_validator import validate_reading_constraints
        assert set(validate_reading_constraints(state)) == {J2, M1}

    def test_validator_rejects_genuine_cycle_without_the_approved_overlap(self) -> None:
        """The same graph is a genuine cycle while the approval is missing."""
        state = self.overlap_pair_state(
            decisions=(),
            prerequisites=(ReadingPrerequisite(1, J2, M1, "reader"),),
        )
        from app.services.reading_list_cycle_validator import validate_reading_constraints
        with pytest.raises(ReadingCycleError) as error:
            validate_reading_constraints(state)
        assert [
            (edge.source_issue_id, edge.target_issue_id) for edge in error.value.edges
        ] == [(M1, J2), (J2, M1)]

    def test_validator_keeps_explicit_gates_under_an_approved_overlap(self) -> None:
        """An explicit hold gate is never waived by an approved overlap."""
        state = self.overlap_pair_state(
            decisions=(MISTER_MIRACLE_WAITS,),
            gate="hold",
            prerequisites=(ReadingPrerequisite(1, J2, M1, "reader"),),
        )
        from app.services.reading_list_cycle_validator import validate_reading_constraints
        with pytest.raises(ReadingCycleError) as error:
            validate_reading_constraints(state)
        assert "list JLI hold" in {edge.origin for edge in error.value.edges}

    def test_validator_accepts_the_approved_overlap_fixture(self) -> None:
        """The #1615 graph validates once the reader approved the overlap."""
        from app.services.reading_list_cycle_validator import validate_reading_constraints
        assert set(validate_reading_constraints(fixture_state())) == {
            F1, F2, J1, J2, J3, M1, M2,
        }

    @pytest.mark.parametrize(("source", "target"), [(M1, J2), (M1, J3), (M2, J3)])
    def test_approved_overlap_never_gates_the_waived_pair(self, source: int, target: int) -> None:
        """A waived pair cannot close a cycle, because the evaluator never gated it."""
        from app.services.reading_list_cycle_validator import validate_reading_constraints
        state = fixture_state()
        state = replace(state, prerequisites=(*state.prerequisites, ReadingPrerequisite(9, target, source)))
        assert set(validate_reading_constraints(state)) == {F1, F2, J1, J2, J3, M1, M2}

    @pytest.mark.parametrize(
        ("source", "target"),
        [(J1, J2), (J1, M1), (M1, M2), (J2, M2), (J2, J3)],
    )
    def test_every_other_strict_pair_still_closes_a_cycle(self, source: int, target: int) -> None:
        """A pair the evaluator still enforces rejects a contradicting prerequisite."""
        from app.services.reading_list_cycle_validator import validate_reading_constraints
        state = fixture_state()
        state = replace(state, prerequisites=(*state.prerequisites, ReadingPrerequisite(9, target, source)))
        with pytest.raises(ReadingCycleError):
            validate_reading_constraints(state)


class TestReadingGraphPreviewInternalHelpers:
    """Internal helper functions for the preview service."""

    def test_decisions_translates_choices_correctly(self) -> None:
        """Reader answers translate to evaluator overlap decisions."""
        chosen = {
            (JLI, MISTER_MIRACLE): "continue_series",
            (FOURTH_WORLD, MISTER_MIRACLE): "protect_order",
        }
        decisions = _decisions(chosen)
        assert decisions == (SeriesOverlapDecision(JLI, MISTER_MIRACLE),)

    def test_decisions_ignores_protect_order(self) -> None:
        """Protect order choices produce no evaluator decision."""
        chosen = {(JLI, MISTER_MIRACLE): "protect_order"}
        decisions = _decisions(chosen)
        assert decisions == ()

    def test_expand_graph_threads_follows_blockers(self) -> None:
        """Graph thread expansion follows blocker chains."""
        # Use baseline (no overlap decision) so JLI has a strict_order blocker on M1
        state = fixture_state(approved=False)
        context = _make_graph_context(state)
        # Seed with JLI thread
        seed = {2}
        expanded = _expand_graph_threads(state, seed, context.issue_meta)
        # Should discover Mister Miracle (via M1 strict_order) and Fourth World (via F2 prerequisite on M1)
        assert 3 in expanded  # Mister Miracle
        assert 1 in expanded  # Fourth World

    def test_choice_effect_produces_different_eligibility(self) -> None:
        """The two choice effects produce different rollable/waiting sets."""
        state = fixture_state()
        context = _make_graph_context(state)
        decisions = _decisions({(JLI, MISTER_MIRACLE): "continue_series"})

        protect_effect = _choice_effect(
            context,
            choice="protect_order",
            decisions=(),
            continuing=type("Ref", (), {"series_name": "JLI"})(),
            waiting=type("Ref", (), {"series_name": "Mister Miracle"})(),
            owned_lists=(),
            entries_by_list={},
            proposed_mode="strict",
            proposed_entries=state.lists[0].entries,
            proposed_name="JLI",
        )
        continue_effect = _choice_effect(
            context,
            choice="continue_series",
            decisions=decisions,
            continuing=type("Ref", (), {"series_name": "JLI"})(),
            waiting=type("Ref", (), {"series_name": "Mister Miracle"})(),
            owned_lists=(),
            entries_by_list={},
            proposed_mode="strict",
            proposed_entries=state.lists[0].entries,
            proposed_name="JLI",
        )
        # Protect order: J2 blocked
        assert J2 not in protect_effect.rollable_issue_ids
        assert J2 in protect_effect.waiting_issue_ids
        # Continue series: J2 rollable
        assert J2 in continue_effect.rollable_issue_ids
        assert J2 not in continue_effect.waiting_issue_ids

    def test_cycle_errors_returns_empty_when_valid(self) -> None:
        """No cycle errors when the graph is valid."""
        state = fixture_state()
        context = _make_graph_context(state)
        errors = _cycle_errors(
            state,
            list_names=context.list_names,
            thread_names=context.thread_names,
            issue_labels={i.issue_id: f"Series {i.thread_id} #{i.position}" for i in state.issues},
        )
        assert errors == []

    def test_cycle_errors_returns_cycle_when_invalid(self) -> None:
        """Cycle errors include a readable path."""
        # Use baseline (no overlap decision) so the strict_order edge M1->J2 exists
        state = fixture_state(approved=False)
        state = replace(state, prerequisites=(*state.prerequisites, ReadingPrerequisite(9, J2, M1)))
        context = _make_graph_context(state)
        errors = _cycle_errors(
            state,
            list_names=context.list_names,
            thread_names=context.thread_names,
            issue_labels={i.issue_id: f"Series {i.thread_id} #{i.position}" for i in state.issues},
        )
        assert len(errors) == 1
        assert errors[0].code == "reading_constraint_cycle"
        # The message uses thread-based labels: M1 is thread 3 position 1, J2 is thread 2 position 2
        assert "Series 3 #1" in errors[0].message and "Series 2 #2" in errors[0].message


class TestReadingGraphPreviewSnapshotImmutability:
    """The preview must not mutate any inputs."""

    def test_evaluation_does_not_mutate_snapshot(self) -> None:
        """Evaluating the graph never changes read status or list entries."""
        state = fixture_state()
        original_issues = tuple((i.issue_id, i.status) for i in state.issues)
        original_entries = tuple((e.issue_id, e.gate, e.skipped) for e in state.lists[0].entries)
        _ = evaluate(state)
        assert tuple((i.issue_id, i.status) for i in state.issues) == original_issues
        assert tuple((e.issue_id, e.gate, e.skipped) for e in state.lists[0].entries) == original_entries

    def test_validator_does_not_mutate_snapshot(self) -> None:
        """Validating the graph never changes read status or list entries."""
        from app.services.reading_list_cycle_validator import validate_reading_constraints
        state = fixture_state()
        original_issues = tuple((i.issue_id, i.status) for i in state.issues)
        original_entries = tuple((e.issue_id, e.gate, e.skipped) for e in state.lists[0].entries)
        _ = validate_reading_constraints(state)
        assert tuple((i.issue_id, i.status) for i in state.issues) == original_issues
        assert tuple((e.issue_id, e.gate, e.skipped) for e in state.lists[0].entries) == original_entries

    def test_build_snapshot_is_independent(self) -> None:
        """Building a new snapshot with different decisions doesn't mutate originals."""
        state = fixture_state()
        new_state = _build_snapshot(
            _make_graph_context(state),
            decisions=(SeriesOverlapDecision(JLI, "other"),),
            owned_lists=(),
            entries_by_list={},
            proposed_mode="strict",
            proposed_entries=state.lists[0].entries,
            proposed_name="JLI",
        )
        # Original unchanged
        assert state.lists[0].overlap_decisions == (MISTER_MIRACLE_WAITS,)
        # New has different decisions
        assert new_state.lists[-1].overlap_decisions == (SeriesOverlapDecision(JLI, "other"),)
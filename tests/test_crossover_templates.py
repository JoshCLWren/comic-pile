"""Tests for deterministic, non-blocking crossover template derivation."""

from app.services.crossover_templates import (
    CBLPlacement,
    TemplateEvidence,
    derive_crossover_template,
)


def _evidence(
    issue_id: int,
    placements: tuple[tuple[str, int], ...],
    story_arc_ids: tuple[str, ...] = (),
    target_story_arc_id: str | None = "xos",
    *,
    thread_id: int | None = None,
    thread_position: int | None = None,
) -> TemplateEvidence:
    return TemplateEvidence(
        issue_id=issue_id,
        cbl_placements=tuple(CBLPlacement(path, position) for path, position in placements),
        story_arc_ids=story_arc_ids,
        target_story_arc_id=target_story_arc_id,
        thread_id=thread_id,
        thread_position=thread_position,
    )


def test_x_of_swords_preserves_24_entry_cbl_order_around_22_chapter_core() -> None:
    """The complete CBL event list keeps two preludes distinct from ComicVine's 22 chapters."""
    path = "x-of-swords.cbl"
    evidence = (
        _evidence(1, ((path, 1),), ("dawn",)),  # Excalibur #12
        _evidence(2, ((path, 2),), ("dawn",)),  # X-Men #12
        _evidence(3, ((path, 3),), ("xos",)),  # Creation #1, chapter 1
        _evidence(4, ((path, 4),), ("xos",)),  # X-Factor #4
        _evidence(5, ((path, 5),), ("xos",)),  # Wolverine #6
        _evidence(6, ((path, 6),), ("xos",)),  # X-Force #13
        _evidence(7, ((path, 7),), ("xos",)),  # Marauders #13
        _evidence(8, ((path, 8),), ("xos",)),  # Hellions #5
        _evidence(9, ((path, 9),), ("xos",)),  # New Mutants #13
        _evidence(10, ((path, 10),), ("xos",)),  # Cable #5
        _evidence(11, ((path, 11),), ("xos",)),  # Excalibur #13
        _evidence(12, ((path, 12),), ("xos",)),  # X-Men #13
        _evidence(13, ((path, 13),), ("xos",)),  # Stasis #1
        _evidence(14, ((path, 14),), ("xos",)),  # X-Men #14
        _evidence(15, ((path, 15),), ("xos",)),  # Marauders #14
        _evidence(16, ((path, 16),), ("xos",)),  # Marauders #15
        _evidence(17, ((path, 17),), ("xos",)),  # Excalibur #14
        _evidence(18, ((path, 18),), ("xos",)),  # Wolverine #7
        _evidence(19, ((path, 19),), ("xos",)),  # X-Force #14
        _evidence(20, ((path, 20),), ("xos",)),  # Hellions #6
        _evidence(21, ((path, 21),), ("xos",)),  # Cable #6
        _evidence(22, ((path, 22),), ("xos",)),  # X-Men #15
        _evidence(23, ((path, 23),), ("xos",)),  # Excalibur #15
        _evidence(24, ((path, 24),), ("xos",)),  # Destruction #1, chapter 22
    )

    template = derive_crossover_template(evidence)

    assert len(template.items) == 24
    assert [item.suggested_position for item in template.items] == list(range(1, 25))
    assert [item.role for item in template.items[:2]] == [
        "context/prelude",
        "context/prelude",
    ]
    assert all(item.role == "core" for item in template.items[2:])
    assert template.items[2].explanation.startswith("ComicVine explicitly tags")
    assert template.items[-1].role == "core"
    assert template.items[0].source_paths == (path,)
    assert template.items[0].cbl_placements == (CBLPlacement(path, 1),)
    assert template.items[0].story_arc_ids == ("dawn",)


def test_x_men_16_reign_of_x_is_context_after_x_of_swords_core() -> None:
    """Reign of X evidence remains inspectable without pretending it is X of Swords core."""
    path = "x-of-swords-with-followup.cbl"
    template = derive_crossover_template(
        (
            _evidence(24, ((path, 24),), ("xos",)),  # Destruction #1
            _evidence(25, ((path, 25),), ("reign-of-x",)),  # X-Men #16
        )
    )

    x_men_16 = template.items[1]
    assert x_men_16.issue_id == 25
    assert x_men_16.story_arc_ids == ("reign-of-x",)
    assert x_men_16.target_story_arc_id == "xos"
    assert x_men_16.role == "epilogue"
    assert "after the explicit ComicVine core" in x_men_16.explanation


def test_conflicting_source_order_is_parallel_candidate_not_serialized() -> None:
    """A less-linear event keeps disagreement as advisory evidence instead of an edge."""
    template = derive_crossover_template(
        (
            _evidence(20, (("a.cbl", 1), ("b.cbl", 4)), target_story_arc_id=None),
            _evidence(30, (("a.cbl", 3), ("b.cbl", 2)), target_story_arc_id=None),
            _evidence(40, (("a.cbl", 5), ("b.cbl", 5)), target_story_arc_id=None),
        )
    )

    assert [(item.issue_id, item.role) for item in template.items] == [
        (20, "unknown"),
        (30, "unknown"),
        (40, "unknown"),
    ]
    assert [
        (item.first_issue_id, item.second_issue_id, item.source_paths)
        for item in template.conflicts
    ] == [(20, 30, ("a.cbl", "b.cbl"))]
    assert [
        (item.first_issue_id, item.second_issue_id, item.source_paths)
        for item in template.parallel_candidates
    ] == [(20, 30, ("a.cbl", "b.cbl"))]
    assert "possible parallel branch" in template.parallel_candidates[0].explanation


def test_same_thread_spines_and_cross_series_intersections_are_advisory() -> None:
    """Series order and cross-series bridges are exposed without generating dependencies."""
    path = "event.cbl"
    template = derive_crossover_template(
        (
            _evidence(
                101,
                ((path, 1),),
                target_story_arc_id=None,
                thread_id=10,
                thread_position=5,
            ),
            _evidence(
                201,
                ((path, 2),),
                target_story_arc_id=None,
                thread_id=20,
                thread_position=8,
            ),
            _evidence(
                102,
                ((path, 3),),
                target_story_arc_id=None,
                thread_id=10,
                thread_position=6,
            ),
        )
    )

    assert len(template.serial_spines) == 1
    spine = template.serial_spines[0]
    assert spine.thread_id == 10
    assert spine.issue_ids == (101, 102)
    assert spine.source_paths == (path,)
    assert "not an added continuity dependency" in spine.explanation

    assert [
        (item.first_issue_id, item.second_issue_id, item.source_paths)
        for item in template.intersections
    ] == [
        (101, 201, (path,)),
        (201, 102, (path,)),
    ]
    assert all("advisory order only" in item.explanation for item in template.intersections)


def test_conflict_detection_binds_positions_to_source_provenance() -> None:
    """Missing membership in one list cannot shift pairwise order comparisons."""
    template = derive_crossover_template(
        (
            _evidence(
                1,
                (("a.cbl", 1), ("b.cbl", 9), ("c.cbl", 2)),
                target_story_arc_id=None,
            ),
            _evidence(
                2,
                (("a.cbl", 3), ("c.cbl", 1)),
                target_story_arc_id=None,
            ),
        )
    )

    assert template.conflicts[0].source_paths == ("a.cbl", "c.cbl")


def test_same_evidence_is_deterministic_and_unknown_stays_unknown() -> None:
    """Input order cannot change output and weak evidence never invents a role."""
    first = _evidence(2, (), target_story_arc_id=None)
    second = _evidence(1, (), target_story_arc_id=None)

    left = derive_crossover_template((first, second))
    right = derive_crossover_template((second, first))

    assert left == right
    assert [item.issue_id for item in left.items] == [1, 2]
    assert all(item.role == "unknown" for item in left.items)

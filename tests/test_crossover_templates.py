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
) -> TemplateEvidence:
    return TemplateEvidence(
        issue_id=issue_id,
        cbl_placements=tuple(CBLPlacement(path, position) for path, position in placements),
        story_arc_ids=story_arc_ids,
        target_story_arc_id=target_story_arc_id,
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


def test_conflicting_source_order_is_inspectable_not_serialized() -> None:
    """A less-linear event keeps disagreement as evidence instead of an edge."""
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

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


def test_x_of_swords_preserves_context_around_explicit_core() -> None:
    """CBL context stays distinct from ComicVine's explicit event membership."""
    evidence = (
        _evidence(12, (("x-of-swords.cbl", 1),), ("dawn",)),
        _evidence(13, (("x-of-swords.cbl", 2),), ("dawn",)),
        _evidence(14, (("x-of-swords.cbl", 3),), ("xos",)),
        _evidence(15, (("x-of-swords.cbl", 24),), ("reign",)),
    )

    template = derive_crossover_template(evidence)

    assert [item.role for item in template.items] == [
        "context/prelude",
        "context/prelude",
        "core",
        "epilogue",
    ]
    assert template.items[2].explanation.startswith("ComicVine explicitly tags")
    assert template.items[0].source_paths == ("x-of-swords.cbl",)


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

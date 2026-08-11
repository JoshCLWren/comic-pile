"""Tests for deterministic, non-blocking crossover template derivation."""

from app.services.crossover_templates import TemplateEvidence, derive_crossover_template


def test_x_of_swords_preserves_context_around_explicit_core() -> None:
    """CBL context stays distinct from ComicVine's explicit event membership."""
    evidence = (
        TemplateEvidence(12, (1,), ("x-of-swords.cbl",), ("dawn",), "xos"),
        TemplateEvidence(13, (2,), ("x-of-swords.cbl",), ("dawn",), "xos"),
        TemplateEvidence(14, (3,), ("x-of-swords.cbl",), ("xos",), "xos"),
        TemplateEvidence(15, (24,), ("x-of-swords.cbl",), ("reign",), "xos"),
    )

    template = derive_crossover_template(evidence)

    assert [item.role for item in template.items] == [
        "context/prelude",
        "context/prelude",
        "core",
        "epilogue",
    ]
    assert template.items[2].explanation.startswith("ComicVine explicitly tags")


def test_conflicting_source_order_is_inspectable_not_serialized() -> None:
    """A less-linear event keeps disagreement as evidence instead of an edge."""
    template = derive_crossover_template(
        (
            TemplateEvidence(20, (1, 4), ("a.cbl", "b.cbl")),
            TemplateEvidence(30, (3, 2), ("a.cbl", "b.cbl")),
            TemplateEvidence(40, (5, 5), ("a.cbl", "b.cbl")),
        )
    )

    assert [(item.issue_id, item.role) for item in template.items] == [
        (20, "unknown"),
        (30, "unknown"),
        (40, "unknown"),
    ]
    assert [(item.first_issue_id, item.second_issue_id) for item in template.conflicts] == [
        (20, 30)
    ]


def test_same_evidence_is_deterministic_and_unknown_stays_unknown() -> None:
    """Input order cannot change output and weak evidence never invents a role."""
    first = TemplateEvidence(2, (), ("context.cbl",))
    second = TemplateEvidence(1, (), ("context.cbl",))

    left = derive_crossover_template((first, second))
    right = derive_crossover_template((second, first))

    assert left == right
    assert [item.issue_id for item in left.items] == [1, 2]
    assert all(item.role == "unknown" for item in left.items)

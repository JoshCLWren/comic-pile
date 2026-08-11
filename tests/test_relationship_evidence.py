"""Tests for provenance-aware relationship evidence derivation."""

from app.services.relationship_evidence import (
    CBLRelationshipObservation,
    RelationshipEvidence,
    _story_arc_ids,
)


def _observation(
    *,
    repository: str,
    path: str,
    first_position: int,
    second_position: int,
) -> CBLRelationshipObservation:
    return CBLRelationshipObservation(
        repository=repository,
        source_path=path,
        revision_sha="abc123",
        first_position=first_position,
        second_position=second_position,
    )


def test_relationship_metrics_preserve_repeated_agreement_and_adjacency() -> None:
    """Repeated source observations remain countable instead of becoming one score."""
    evidence = RelationshipEvidence(
        first_issue_id=10,
        second_issue_id=20,
        cbl_observations=(
            _observation(
                repository="official/lists",
                path="event-a.cbl",
                first_position=3,
                second_position=4,
            ),
            _observation(
                repository="community/lists",
                path="event-a.cbl",
                first_position=8,
                second_position=11,
            ),
        ),
        shared_story_arc_ids=(),
        same_thread=False,
        serial_order=None,
    )

    assert evidence.cooccurrence_count == 2
    assert evidence.distinct_source_count == 2
    assert evidence.ordered_before_count == 2
    assert evidence.ordered_after_count == 0
    assert evidence.adjacent_count == 1
    assert evidence.has_order_conflict is False


def test_relationship_metrics_preserve_conflicting_relative_order() -> None:
    """Contradictory source orders stay explicit and inspectable."""
    evidence = RelationshipEvidence(
        first_issue_id=10,
        second_issue_id=20,
        cbl_observations=(
            _observation(
                repository="official/lists",
                path="event-a.cbl",
                first_position=2,
                second_position=5,
            ),
            _observation(
                repository="community/lists",
                path="event-a-alt.cbl",
                first_position=9,
                second_position=6,
            ),
        ),
        shared_story_arc_ids=(),
        same_thread=False,
        serial_order=None,
    )

    assert evidence.ordered_before_count == 1
    assert evidence.ordered_after_count == 1
    assert evidence.has_order_conflict is True


def test_story_arc_membership_is_separate_from_cbl_ordering() -> None:
    """Story-arc-only evidence is represented without manufacturing CBL order."""
    evidence = RelationshipEvidence(
        first_issue_id=10,
        second_issue_id=20,
        cbl_observations=(),
        shared_story_arc_ids=("4045",),
        same_thread=False,
        serial_order=None,
    )

    assert evidence.cooccurrence_count == 0
    assert evidence.explicit_story_arc_count == 1
    assert evidence.ordered_before_count == 0


def test_same_thread_serial_context_does_not_become_external_order_evidence() -> None:
    """Same-thread order is contextual and does not inflate external metrics."""
    evidence = RelationshipEvidence(
        first_issue_id=10,
        second_issue_id=20,
        cbl_observations=(),
        shared_story_arc_ids=(),
        same_thread=True,
        serial_order="before",
    )

    assert evidence.same_thread is True
    assert evidence.serial_order == "before"
    assert evidence.cooccurrence_count == 0
    assert evidence.adjacent_count == 0


def test_story_arc_id_normalization_ignores_malformed_metadata() -> None:
    """Hydration oddities cannot create bogus story-arc identities."""
    metadata: dict[str, object] = {
        "story_arcs": [
            {"id": 123},
            {"id": " 456 "},
            {"id": ""},
            {"name": "missing id"},
            "unexpected",
        ]
    }

    assert _story_arc_ids(metadata) == {"123", "456"}
    assert _story_arc_ids({"story_arcs": "not-a-list"}) == set()

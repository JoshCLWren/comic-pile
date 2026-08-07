"""Focused validation coverage for generalized continuity-rule schemas."""

import pytest
from pydantic import ValidationError

from app.schemas.continuity_rule import ContinuityRuleCreate


@pytest.mark.parametrize(
    ("source_type", "target_type"),
    [
        ("issue", "issue"),
        ("issue", "crossover"),
        ("crossover", "issue"),
        ("crossover", "crossover"),
    ],
)
def test_continuity_rule_accepts_all_node_pairings(
    source_type: str,
    target_type: str,
) -> None:
    """Accept all supported node pairings."""
    rule = ContinuityRuleCreate(
        source_type=source_type,
        source_id=1,
        target_type=target_type,
        target_id=2,
        satisfaction_type="item_read",
    )

    assert rule.source_type == source_type
    assert rule.target_type == target_type


def test_checkpoint_requires_checkpoint_issue() -> None:
    """Checkpoint satisfaction requires a checkpoint issue ID."""
    with pytest.raises(ValidationError, match="checkpoint_issue_id is required"):
        ContinuityRuleCreate(
            source_type="issue",
            source_id=1,
            target_type="crossover",
            target_id=2,
            satisfaction_type="checkpoint",
        )


def test_checkpoint_issue_is_rejected_for_other_policies() -> None:
    """Checkpoint issue ID is rejected for non-checkpoint policies."""
    with pytest.raises(ValidationError, match="checkpoint_issue_id is only valid"):
        ContinuityRuleCreate(
            source_type="issue",
            source_id=1,
            target_type="issue",
            target_id=2,
            satisfaction_type="item_read",
            checkpoint_issue_id=3,
        )


def test_selected_members_are_required_and_deduplicated() -> None:
    """Selected-member rules require at least one member and deduplicate IDs."""
    rule = ContinuityRuleCreate(
        source_type="crossover",
        source_id=1,
        target_type="issue",
        target_id=2,
        satisfaction_type="selected_members_read",
        selected_member_issue_ids=[3, 4, 3],
    )

    assert rule.selected_member_issue_ids == [3, 4]

    with pytest.raises(ValidationError, match="require at least one issue"):
        ContinuityRuleCreate(
            source_type="crossover",
            source_id=1,
            target_type="issue",
            target_id=2,
            satisfaction_type="selected_members_read",
        )


def test_self_rule_is_rejected() -> None:
    """Self-targeting continuity rules are rejected."""
    with pytest.raises(ValidationError, match="cannot target its own source node"):
        ContinuityRuleCreate(
            source_type="crossover",
            source_id=7,
            target_type="crossover",
            target_id=7,
            satisfaction_type="all_members_read",
        )

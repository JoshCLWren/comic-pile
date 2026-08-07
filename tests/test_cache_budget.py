"""Tests for conservative Redis command-budget projections."""

import pytest

from app.cache_budget import (
    FREE_TIER_COMMAND_LIMIT,
    REPRESENTATIVE_FLOW_BUDGETS,
    cycle_budget_is_safe,
    projected_cycle_commands,
    safe_cycle_command_limit,
)


def test_representative_flow_command_ceilings_are_bounded() -> None:
    expected = {
        "initial_authenticated_bootstrap": 9,
        "queue_load": 3,
        "roll": 4,
        "snooze": 1,
        "rate": 1,
        "thread_create_update_reposition": 1,
        "issue_create_reorder_read_unread": 1,
        "dependency_and_crossover_mutation": 1,
    }

    actual = {
        name: budget.max_commands
        for name, budget in REPRESENTATIVE_FLOW_BUDGETS.items()
    }
    assert actual == expected


def test_projection_uses_worst_case_flow_ceilings() -> None:
    observed = {
        "initial_authenticated_bootstrap": 10,
        "queue_load": 20,
        "roll": 30,
        "snooze": 5,
        "rate": 25,
        "thread_create_update_reposition": 2,
        "issue_create_reorder_read_unread": 8,
        "dependency_and_crossover_mutation": 1,
    }

    assert projected_cycle_commands(observed) == 311


def test_default_safe_limit_reserves_35_percent_headroom() -> None:
    assert safe_cycle_command_limit() == 325_000
    assert safe_cycle_command_limit() < FREE_TIER_COMMAND_LIMIT


def test_cycle_budget_flags_projection_over_safe_limit() -> None:
    assert cycle_budget_is_safe({"rate": 325_000})
    assert not cycle_budget_is_safe({"rate": 325_001})


@pytest.mark.parametrize(
    "flow_counts",
    [
        {"unknown": 1},
        {"rate": -1},
    ],
)
def test_projection_rejects_unbudgeted_or_invalid_traffic(
    flow_counts: dict[str, int],
) -> None:
    with pytest.raises(ValueError):
        projected_cycle_commands(flow_counts)

"""Conservative Redis command budgets for representative ComicPile flows.

The generation cache deliberately uses small, deterministic command counts.  This
module keeps the expected upper bounds in one place so tests, diagnostics, and
operator documentation can reason about the same numbers without exposing cache
keys or user data.
"""

from __future__ import annotations

from dataclasses import dataclass

FREE_TIER_COMMAND_LIMIT = 500_000
DEFAULT_HEADROOM_FRACTION = 0.35


@dataclass(frozen=True, slots=True)
class FlowCommandBudget:
    """Maximum remote-cache commands for one representative user flow.

    ``read_misses`` assumes each cache miss is stored, making it the more expensive
    three-command generation-cache path. ``read_hits`` cost two commands each.
    Each distinct mutated user namespace costs one generation increment.
    """

    read_hits: int = 0
    read_misses: int = 0
    invalidated_users: int = 0

    def __post_init__(self) -> None:
        if min(self.read_hits, self.read_misses, self.invalidated_users) < 0:
            raise ValueError("Cache flow command counts cannot be negative")

    @property
    def max_commands(self) -> int:
        """Return the conservative remote-command ceiling for the flow."""
        return self.read_hits * 2 + self.read_misses * 3 + self.invalidated_users


# These are per-flow cache ceilings, not expected averages.  A mutation is charged
# one generation bump even when it invalidates many logical cache families.
REPRESENTATIVE_FLOW_BUDGETS: dict[str, FlowCommandBudget] = {
    "initial_authenticated_bootstrap": FlowCommandBudget(read_misses=3),
    "queue_load": FlowCommandBudget(read_misses=1),
    "roll": FlowCommandBudget(read_misses=1, invalidated_users=1),
    "snooze": FlowCommandBudget(invalidated_users=1),
    "rate": FlowCommandBudget(invalidated_users=1),
    "thread_create_update_reposition": FlowCommandBudget(invalidated_users=1),
    "issue_create_reorder_read_unread": FlowCommandBudget(invalidated_users=1),
    "dependency_and_crossover_mutation": FlowCommandBudget(invalidated_users=1),
}


def projected_cycle_commands(flow_counts: dict[str, int]) -> int:
    """Project remote commands for one billing cycle from observed flow counts.

    Unknown flows are rejected so newly introduced cache-bearing behavior cannot be
    silently omitted from the budget model.
    """
    total = 0
    for flow_name, count in flow_counts.items():
        if count < 0:
            raise ValueError("Observed flow counts cannot be negative")
        try:
            budget = REPRESENTATIVE_FLOW_BUDGETS[flow_name]
        except KeyError as exc:
            raise ValueError(f"Unknown cache flow: {flow_name}") from exc
        total += budget.max_commands * count
    return total


def safe_cycle_command_limit(
    *,
    free_tier_limit: int = FREE_TIER_COMMAND_LIMIT,
    headroom_fraction: float = DEFAULT_HEADROOM_FRACTION,
) -> int:
    """Return the maximum planned command usage after reserving safety headroom."""
    if free_tier_limit <= 0:
        raise ValueError("Free-tier command limit must be positive")
    if not 0 < headroom_fraction < 1:
        raise ValueError("Headroom fraction must be between zero and one")
    return int(free_tier_limit * (1 - headroom_fraction))


def cycle_budget_is_safe(
    flow_counts: dict[str, int],
    *,
    free_tier_limit: int = FREE_TIER_COMMAND_LIMIT,
    headroom_fraction: float = DEFAULT_HEADROOM_FRACTION,
) -> bool:
    """Return whether observed traffic fits beneath the conservative safe limit."""
    return projected_cycle_commands(flow_counts) <= safe_cycle_command_limit(
        free_tier_limit=free_tier_limit,
        headroom_fraction=headroom_fraction,
    )

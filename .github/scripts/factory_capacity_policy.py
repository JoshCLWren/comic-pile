"""Demand-driven capacity allocation for ComicPile factories."""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class FleetDemand:
    """Current executable work and idle worker capacity."""

    completion: int
    production: int
    idle_workers: int

    def __post_init__(self) -> None:
        if self.completion < 0 or self.production < 0 or self.idle_workers < 0:
            raise ValueError("factory demand counts cannot be negative")

    @property
    def total(self) -> int:
        return self.completion + self.production

    @property
    def completion_share(self) -> float:
        """Return the fraction of executable demand that is completion work."""
        if self.total == 0:
            return 0.0
        return self.completion / self.total


def completion_worker_target(demand: FleetDemand) -> int:
    """Allocate idle workers proportionally to live completion demand.

    The allocator is work-conserving and derived from current queue figures:
    - no completion demand consumes no completion workers;
    - no production demand lets completion consume the idle fleet;
    - mixed demand receives a proportional share of idle capacity;
    - any non-empty completion queue gets at least one worker when capacity exists;
    - assignments never exceed either completion queue depth or idle capacity.
    """
    if demand.completion == 0 or demand.idle_workers == 0:
        return 0
    if demand.production == 0:
        return min(demand.completion, demand.idle_workers)

    proportional = math.ceil(demand.idle_workers * demand.completion_share)
    return min(demand.completion, demand.idle_workers, max(1, proportional))


def production_worker_target(demand: FleetDemand) -> int:
    """Return idle capacity left for fresh implementation work."""
    return max(0, demand.idle_workers - completion_worker_target(demand))

"""Executable production cache provider decision rule (issue #1785).

The go/no-go memo in ``docs/CACHE_PROVIDER_DECISION_2026-08.md`` records the
production provider decision and the numbers behind it. Keeping the rule in code
makes the memo's conclusions reproducible the moment the outstanding inputs land
(post-reset latency measurements and a route-traffic census):

- :data:`PRODUCTION_CACHE_PROVIDER` is the current memo conclusion. A test pins
  the runtime default to this value so production configuration matches the memo.
- :func:`provider_recommendation` applies the latency thresholds documented in
  ``docs/CACHE_LOOKUP_LATENCY_2026-08.md``.
- :func:`project_monthly_cache_commands` multiplies a monthly per-flow traffic
  census by the ceilings in ``docs/CACHE_COMMAND_BUDGET.md`` and reports whether
  the projection keeps the documented application budget and provider headroom.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from app.cache_metrics import (
    CACHE_FLOW_COMMAND_CEILINGS,
    CONSERVATIVE_MONTHLY_COMMAND_BUDGET,
)
from app.config import CacheProvider

LatencyVerdict = Literal["upstash", "postgres", "investigate"]

# Current production provider per the provider-decision memo after the #2216
# GO. Code defaults remain Postgres; production env must set CACHE_PROVIDER=redis.
PRODUCTION_CACHE_PROVIDER: CacheProvider = "redis"

# Latency decision thresholds from docs/CACHE_LOOKUP_LATENCY_2026-08.md.
UPSTASH_FASTER_FACTOR = 2.0
NEON_ABSOLUTE_FAST_MS = 3.0
VARIANCE_INVESTIGATE_FACTOR = 5.0


@dataclass(frozen=True, slots=True)
class LatencySample:
    """One measured p50/p95 distribution pair for a cache path.

    Attributes:
        p50_ms: Median wall-clock latency in milliseconds.
        p95_ms: 95th-percentile wall-clock latency in milliseconds.
    """

    p50_ms: float
    p95_ms: float


@dataclass(frozen=True, slots=True)
class CacheCommandProjection:
    """One projected monthly command demand versus the application budget.

    Attributes:
        total_commands: Projected monthly provider commands from the census.
        budget_commands: Conservative monthly application budget from
            ``docs/CACHE_COMMAND_BUDGET.md``.
    """

    total_commands: int
    budget_commands: int = CONSERVATIVE_MONTHLY_COMMAND_BUDGET

    @property
    def within_budget(self) -> bool:
        """Return whether the projection stays below the application budget.

        The re-enable gate requires a projection below 350,000 commands so the
        150,000-command provider headroom is preserved, hence a strict less-than.
        """
        return self.total_commands < self.budget_commands


def provider_recommendation(upstash: LatencySample, neon: LatencySample) -> LatencyVerdict:
    """Return the provider favored by the documented latency decision rule.

    The rule mirrors ``docs/CACHE_LOOKUP_LATENCY_2026-08.md``: Upstash is
    meaningfully faster only when its p50 is below 2x the Neon point SELECT p50
    and the Neon absolute is above 3 ms; otherwise Neon point reads are not
    meaningfully slower. Either path with a p95/p50 ratio above 5x indicates
    unstable measurements that must be investigated before deciding.

    Args:
        upstash: Measured p50/p95 for an Upstash REST GET from the Vercel region.
        neon: Measured p50/p95 for a Neon point SELECT from the same vantage.

    Returns:
        ``"upstash"`` when Upstash is meaningfully faster, ``"postgres"`` when
        Neon point reads are not meaningfully slower, and ``"investigate"`` when
        either path shows unstable variance.

    Raises:
        ValueError: If any p50 sample is not positive.
    """
    for label, sample in (("upstash", upstash), ("neon", neon)):
        if sample.p50_ms <= 0:
            raise ValueError(f"{label} p50 latency must be positive")
        if sample.p95_ms / sample.p50_ms > VARIANCE_INVESTIGATE_FACTOR:
            return "investigate"
    if upstash.p50_ms < UPSTASH_FASTER_FACTOR * neon.p50_ms and neon.p50_ms > NEON_ABSOLUTE_FAST_MS:
        return "upstash"
    return "postgres"


def project_monthly_cache_commands(
    monthly_flow_counts: Mapping[str, int],
) -> CacheCommandProjection:
    """Project monthly provider command demand from a per-flow census.

    Args:
        monthly_flow_counts: Observed monthly count per documented cache flow.
            Unknown flow names are rejected so a census cannot silently invent
            demand beyond the ceilings in ``docs/CACHE_COMMAND_BUDGET.md``.

    Returns:
        Projection compared against the conservative monthly application budget.

    Raises:
        ValueError: When a flow is undocumented or a count is negative.
    """
    known_flows = set(CACHE_FLOW_COMMAND_CEILINGS)
    unknown = set(monthly_flow_counts) - known_flows
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ValueError(f"undocumented cache flow(s): {names}")
    total = 0
    for flow, count in monthly_flow_counts.items():
        if count < 0:
            raise ValueError(f"cache flow count must be non-negative: {flow}={count}")
        total += count * CACHE_FLOW_COMMAND_CEILINGS[flow]
    return CacheCommandProjection(total_commands=total)
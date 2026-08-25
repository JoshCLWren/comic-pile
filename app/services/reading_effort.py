"""Reading-effort estimate vocabulary and neutral resolution.

A reading-effort estimate describes how mentally/time demanding a candidate
comic is expected to be for the reader. Estimates are observational inputs to
later personalization phases; they never alter roll selection in this phase.

Estimates carry an explicit source so later analysis can weigh them by trust:

- ``observed_issue``: derived from prior reads of the exact issue.
- ``observed_thread``: derived from prior reads of the thread/series.
- ``era_prior``: conservative publication-era fallback from external metadata.
- ``unknown``: no estimator could produce data; the neutral case.

The observed-history aggregator (#1702) and the ComicVine publication-era
fallback (#1703) will register real estimators ahead of the neutral fallback.
Until then every resolution returns :data:`NEUTRAL_EFFORT_ESTIMATE`, which is
the contract this module guarantees: missing estimates stay neutral and must
never block a Roll.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Thread

EFFORT_SOURCE_OBSERVED_ISSUE = "observed_issue"
EFFORT_SOURCE_OBSERVED_THREAD = "observed_thread"
EFFORT_SOURCE_ERA_PRIOR = "era_prior"
EFFORT_SOURCE_UNKNOWN = "unknown"

KNOWN_EFFORT_SOURCES = frozenset(
    {
        EFFORT_SOURCE_OBSERVED_ISSUE,
        EFFORT_SOURCE_OBSERVED_THREAD,
        EFFORT_SOURCE_ERA_PRIOR,
        EFFORT_SOURCE_UNKNOWN,
    }
)

EFFORT_BAND_LIGHT = "light"
EFFORT_BAND_BALANCED = "balanced"
EFFORT_BAND_DEEP = "deep"

KNOWN_EFFORT_BANDS = frozenset(
    {
        EFFORT_BAND_LIGHT,
        EFFORT_BAND_BALANCED,
        EFFORT_BAND_DEEP,
    }
)


@dataclass(frozen=True)
class EffortEstimate:
    """Bounded reading-effort estimate attached to recommendation context.

    Attributes:
        minutes: Estimated reading effort in minutes, or ``None`` when unknown.
        band: One of :data:`KNOWN_EFFORT_BANDS`, or ``None`` when unknown.
        source: One of :data:`KNOWN_EFFORT_SOURCES`; ``unknown`` when neutral.
        confidence: Estimate confidence in ``[0.0, 1.0]``, or ``None``.
    """

    minutes: float | None
    band: str | None
    source: str
    confidence: float | None

    def __post_init__(self) -> None:
        """Validate effort source, band, and confidence values."""
        if self.source not in KNOWN_EFFORT_SOURCES:
            raise ValueError(f"Unknown effort source: {self.source!r}")
        if self.band is not None and self.band not in KNOWN_EFFORT_BANDS:
            raise ValueError(f"Unknown effort band: {self.band!r}")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Effort confidence must be within [0, 1]: {self.confidence!r}")

    def to_context(self) -> dict[str, float | str | None]:
        """Return the JSON-safe context payload for this estimate."""
        return {
            "minutes": self.minutes,
            "band": self.band,
            "source": self.source,
            "confidence": self.confidence,
        }


NEUTRAL_EFFORT_ESTIMATE = EffortEstimate(
    minutes=None,
    band=None,
    source=EFFORT_SOURCE_UNKNOWN,
    confidence=None,
)


class EffortResolver(Protocol):
    """Protocol for future reading-effort estimators."""

    async def __call__(
        self,
        db: AsyncSession,
        candidates: Sequence[Thread],
    ) -> dict[int, EffortEstimate]:
        """Return estimates keyed by thread ID for the bounded roll pool."""
        ...


async def resolve_candidate_efforts(
    db: AsyncSession,
    candidates: Sequence[Thread],
) -> dict[int, EffortEstimate]:
    """Resolve reading-effort estimates for the current bounded die pool.

    Resolution is observational only: it must never raise into the Roll path
    and must never change selection behavior. Any resolver failure degrades to
    the neutral estimate for that candidate.

    Args:
        db: Async database session.
        candidates: Bounded candidate threads in exact selection order.

    Returns:
        Mapping of thread ID to :class:`EffortEstimate` for candidates with a
        non-neutral estimate. Candidates absent from the mapping are neutral.
    """
    _ = db
    _ = candidates
    return {}


def selected_effort_estimate(
    efforts_by_thread: Mapping[int, EffortEstimate],
    selected_thread_id: int | None,
) -> EffortEstimate:
    """Return the estimate recorded for the selected candidate, else neutral."""
    if selected_thread_id is None:
        return NEUTRAL_EFFORT_ESTIMATE
    return efforts_by_thread.get(selected_thread_id, NEUTRAL_EFFORT_ESTIMATE)

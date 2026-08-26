"""Recommendation selection control path for the Roll dice pool.

This module is the explicit control path that preserves today's unweighted
random Roll behavior while the personalized-Roll roadmap (#1685) adds
contextual weighting around it. The die remains the hard candidate-pool
boundary: callers pass an already-bounded pool size and this module never
selects outside it.

Selection modes:

- ``legacy_uniform``: ``balanced`` bandwidth with ``balanced``/default intent.
  Neutral by contract: no factor may bias this draw, so it is byte-for-byte
  the legacy uniform roll (a single ``randint(0, pool_size - 1)`` call).
- ``pure_random_bypass``: the ``random`` intent escape hatch. Contextual
  weights are bypassed completely, reproducing legacy unweighted selection
  inside the bounded pool.
- ``contextual_weighted``: reserved for later phases (#1712, #1715, #1761).
  Valid positive weights supplied by the caller may shape the draw; missing,
  invalid, or unusable weights always fall back safely to the exact legacy
  uniform draw.

The module is intentionally pure: no database, network, or framework
dependencies, so seeded regression tests can compare legacy and control-mode
streams exactly.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

DEFAULT_BANDWIDTH = "balanced"
DEFAULT_INTENT = "balanced"


class Bandwidth(StrEnum):
    """Reading-bandwidth vocabulary from the personalized-Roll roadmap."""

    LIGHT = "light"
    BALANCED = "balanced"
    DEEP = "deep"


class Intent(StrEnum):
    """Reading-intent vocabulary from the personalized-Roll roadmap."""

    BALANCED = "balanced"
    MOMENTUM = "momentum"
    FAMILIAR = "familiar"
    EXPLORE = "explore"
    RANDOM = "random"


class SelectionMode(StrEnum):
    """Resolved control path for one bounded-pool selection."""

    LEGACY_UNIFORM = "legacy_uniform"
    PURE_RANDOM_BYPASS = "pure_random_bypass"
    CONTEXTUAL_WEIGHTED = "contextual_weighted"


class RandomSource(Protocol):
    """Minimal RNG interface shared by the ``random`` module and ``Random``."""

    def randint(self, a: int, b: int) -> int:
        """Return a random integer N such that ``a <= N <= b``.

        Args:
            a: Inclusive lower bound.
            b: Inclusive upper bound.

        Returns:
            A uniformly distributed integer in the closed interval.
        """
        ...

    def random(self) -> float:
        """Return a random float in the half-open interval ``[0.0, 1.0)``.

        Returns:
            A uniformly distributed float.
        """
        ...


@dataclass(frozen=True)
class SelectionOutcome:
    """Result of one bounded-pool selection.

    Attributes:
        index: Zero-based position inside the bounded candidate pool.
        result: One-based die face shown to the reader (``index + 1``).
        mode: Control path that produced this selection.
        bandwidth: Normalized bandwidth used for mode resolution.
        intent: Normalized intent used for mode resolution.
        weights_applied: Whether contextual weights actually shaped the draw.
            Always ``False`` for both control modes.
    """

    index: int
    result: int
    mode: SelectionMode
    bandwidth: Bandwidth
    intent: Intent
    weights_applied: bool


def normalize_bandwidth(value: str | Bandwidth | None) -> Bandwidth:
    """Normalize a raw bandwidth value to the canonical enum.

    Args:
        value: Raw bandwidth value. ``None`` means the default (balanced).

    Returns:
        The canonical :class:`Bandwidth` member.

    Raises:
        ValueError: If the value is not a known bandwidth.
    """
    if value is None:
        return Bandwidth(DEFAULT_BANDWIDTH)
    try:
        return Bandwidth(value)
    except ValueError as error:
        raise ValueError(f"Unknown bandwidth: {value!r}") from error


def normalize_intent(value: str | Intent | None) -> Intent:
    """Normalize a raw intent value to the canonical enum.

    Args:
        value: Raw intent value. ``None`` means the default (balanced).

    Returns:
        The canonical :class:`Intent` member.

    Raises:
        ValueError: If the value is not a known intent.
    """
    if value is None:
        return Intent(DEFAULT_INTENT)
    try:
        return Intent(value)
    except ValueError as error:
        raise ValueError(f"Unknown intent: {value!r}") from error


def resolve_selection_mode(
    bandwidth: str | Bandwidth | None = None,
    intent: str | Intent | None = None,
) -> SelectionMode:
    """Resolve which control path governs one selection.

    Rules, in priority order:

    1. The ``random`` intent is a clean escape hatch: it bypasses contextual
       weights completely regardless of bandwidth.
    2. ``balanced`` bandwidth with ``balanced``/default intent stays neutral:
       no factor may bias this draw unless a later phase explicitly adds one.
    3. Any other combination takes the contextual-weighted path where caller
       supplied weights may shape the draw (subject to safe fallback).

    Args:
        bandwidth: Raw bandwidth value; ``None`` means balanced.
        intent: Raw intent value; ``None`` means balanced.

    Returns:
        The resolved :class:`SelectionMode`.
    """
    resolved_bandwidth = normalize_bandwidth(bandwidth)
    resolved_intent = normalize_intent(intent)
    if resolved_intent is Intent.RANDOM:
        return SelectionMode.PURE_RANDOM_BYPASS

    if resolved_bandwidth is Bandwidth.BALANCED and resolved_intent is Intent.BALANCED:
        return SelectionMode.LEGACY_UNIFORM

    return SelectionMode.CONTEXTUAL_WEIGHTED


def normalize_weights(
    weights: Sequence[float] | None,
    pool_size: int,
) -> list[float] | None:
    """Validate contextual weights for use in one weighted draw.

    Usable weights are a non-string sequence of exactly ``pool_size`` finite,
    strictly positive floats with a positive total.

    Args:
        weights: Raw candidate weights, or ``None`` when absent.
        pool_size: Number of candidates in the bounded pool.

    Returns:
        The validated per-candidate weight list, or ``None`` when the input
        is absent or invalid.
    """
    if weights is None or pool_size < 1:
        return None
    if isinstance(weights, (str, bytes)):
        return None
    if not isinstance(weights, Sequence) or len(weights) != pool_size:
        return None

    normalized: list[float] = []
    total = 0.0
    for weight in weights:
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            return None
        value = float(weight)
        if not math.isfinite(value) or value <= 0.0:
            return None
        normalized.append(value)
        total += value

    if total <= 0.0:
        return None
    return normalized


def _randint(rng: RandomSource | None, low: int, high: int) -> int:
    """Draw one uniform integer through the configured RNG source.

    Args:
        rng: Caller RNG, or ``None`` to use the shared stdlib ``random`` module.
        low: Inclusive lower bound.
        high: Inclusive upper bound.

    Returns:
        A uniformly distributed integer in ``[low, high]``.
    """
    source = rng if rng is not None else random
    return source.randint(low, high)


def _random_float(rng: RandomSource | None) -> float:
    """Draw one uniform float through the configured RNG source.

    Args:
        rng: Caller RNG, or ``None`` to use the shared stdlib ``random`` module.

    Returns:
        A uniformly distributed float in ``[0.0, 1.0)``.
    """
    source = rng if rng is not None else random
    return source.random()


def select_from_pool(
    pool_size: int,
    *,
    bandwidth: str | Bandwidth | None = None,
    intent: str | Intent | None = None,
    weights: Sequence[float] | None = None,
    rng: RandomSource | None = None,
) -> SelectionOutcome:
    """Select one candidate from an already-bounded pool.

    Both control modes reproduce the legacy Roll draw exactly: a single
    ``randint(0, pool_size - 1)`` call, so identical seeds produce identical
    selections. Only the contextual-weighted path may consume weights, and
    only valid strictly positive weights can shape it.

    Args:
        pool_size: Number of candidates in the bounded pool (>= 1).
        bandwidth: Reading bandwidth context; ``None`` means balanced.
        intent: Reading intent context; ``None`` means balanced.
        weights: Optional contextual weights aligned with the pool order.
            Ignored completely under both control modes.
        rng: RNG source for deterministic tests; ``None`` uses the shared
            stdlib ``random`` module exactly like the legacy endpoint.

    Returns:
        A :class:`SelectionOutcome` recording the chosen index plus the
        resolved mode and whether any weight influenced the draw.

    Raises:
        ValueError: If ``pool_size`` is below one, or the bandwidth/intent
            values are unknown.
    """
    if pool_size < 1:
        raise ValueError(f"pool_size must be >= 1, got {pool_size}")

    resolved_mode = resolve_selection_mode(bandwidth, intent)
    normalized_bandwidth = normalize_bandwidth(bandwidth)
    normalized_intent = normalize_intent(intent)

    usable_weights: list[float] | None = None
    if resolved_mode is SelectionMode.CONTEXTUAL_WEIGHTED:
        usable_weights = normalize_weights(weights, pool_size)

    if resolved_mode is not SelectionMode.CONTEXTUAL_WEIGHTED or usable_weights is None:
        index = _randint(rng, 0, pool_size - 1)
        return SelectionOutcome(
            index=index,
            result=index + 1,
            mode=resolved_mode,
            bandwidth=normalized_bandwidth,
            intent=normalized_intent,
            weights_applied=False,
        )

    total = sum(usable_weights)
    pick = _random_float(rng) * total
    cumulative = 0.0
    selected = pool_size - 1
    for candidate_index, weight in enumerate(usable_weights):
        cumulative += weight
        if pick < cumulative:
            selected = candidate_index
            break

    return SelectionOutcome(
        index=selected,
        result=selected + 1,
        mode=resolved_mode,
        bandwidth=normalized_bandwidth,
        intent=normalized_intent,
        weights_applied=True,
    )

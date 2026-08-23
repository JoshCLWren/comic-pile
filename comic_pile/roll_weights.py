"""Pure weight calculation for contextual roll selection."""

import logging
import random
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from app.models import Thread


logger = logging.getLogger(__name__)

PoolRow = tuple[Any, int, Any]
BandwidthMode = Literal["light", "balanced", "deep"]

WEIGHT_MIN = 0.1
WEIGHT_NEUTRAL = 1.0
WEIGHT_CAP = 10.0

_BALANCED_MODES = frozenset(["balanced"])
_LIGHT_MODES = frozenset(["light"])
_DEEP_MODES = frozenset(["deep"])


def calculate_weights(
    pool_rows: list[PoolRow],
    bandwidth: BandwidthMode,
    rng: random.Random | None = None,
) -> list[float]:
    """Compute per-candidate selection weights for the given bandwidth mode.

    Effort is proxied by the unread issue count carried in each pool row.
    Lower effort means fewer unread issues and less reading fatigue.

    Mode mapping (effort from 0 to unbounded, proxy = unread_count):

        light  – weight rises as effort falls; favors quick, low-effort reads.
        balanced – all candidates receive neutral weight regardless of effort.
        deep   – weight rises with effort up to the cap; promotes immersive
                 reading without ever excluding the lower-effort candidates.

    Weights are clamped to [WEIGHT_MIN, WEIGHT_CAP] so no single candidate
    can monopolize or zero-out the selection.

    Args:
        pool_rows: Pre-bounded candidate pool ordered by queue position.
        bandwidth: Reader bandwidth mode: "light", "balanced", or "deep".
        rng: Optional per-call random-number generator for reproducibility.
            Defaults to the global ``random`` module when None.

    Returns:
        List of positive floats, one per pool_rows entry.

    Raises:
        ValueError: If pool_rows is empty or bandwidth is not a valid mode.
    """
    if not pool_rows:
        raise ValueError("pool_rows must contain at least one candidate")

    if bandwidth not in ("light", "balanced", "deep"):
        raise ValueError(
            f"Unknown bandwidth mode '{bandwidth}'. "
            f"Expected 'light', 'balanced', or 'deep'."

        )

    if rng is None:
        rng = random

    efforts = [row[1] or 0 for row in pool_rows]
    max_effort = max(efforts) if efforts else 1
    if max_effort <= 0:
        max_effort = 1

    def _compute_weight(effort: int) -> float:
        if bandwidth in _BALANCED_MODES:
            return WEIGHT_NEUTRAL
        normalized = min(effort / max_effort, 1.0)
        if bandwidth in _LIGHT_MODES:
            weight = 1.0 + 3.0 * (1.0 - normalized)
        elif bandwidth in _DEEP_MODES:
            weight = 0.5 + 0.5 * normalized * WEIGHT_CAP
        else:
            return WEIGHT_NEUTRAL
        return max(WEIGHT_MIN, min(WEIGHT_CAP, weight))

    weights = [_compute_weight(e) for e in efforts]
    return weights


def select_weighted(
    pool_rows: list[PoolRow],
    bandwidth: BandwidthMode,
    rng: random.Random | None = None,
) -> tuple[int, PoolRow, float]:
    """Choose one candidate from the bounded pool using weighted selection.

    Falls back uniformly (all-equal weights) when weights are uniform across
    all candidates, balanced mode is active, or only a single candidate exists.

    Args:
        pool_rows: Pre-bounded candidate pool ordered by queue position.
        bandwidth: Reader bandwidth mode: "light", "balanced", or "deep".
        rng: Optional per-call random-number generator for reproducibility.
            Defaults to the global ``random`` module when None.

    Returns:
        Tuple of (selected_index, selected_pool_row, weight_at_selected_index).

    Raises:
        ValueError: If pool_rows is empty or bandwidth is invalid.
    """
    weights = calculate_weights(pool_rows, bandwidth, rng=rng)
    if rng is None:
        rng = random

    if len(pool_rows) == 1:
        return 0, pool_rows[0], weights[0]

    uniform = len(set(round(w, 6) for w in weights)) == 1
    if uniform:
        idx = rng.randint(0, len(pool_rows) - 1)
        return idx, pool_rows[idx], weights[idx]

    total_weight = sum(weights)
    if total_weight <= 0:
        idx = rng.randint(0, len(pool_rows) - 1)
        return idx, pool_rows[idx], weights[idx]

    chosen_idx = rng.choices(range(len(pool_rows)), weights=weights, k=1)[0]
    return chosen_idx, pool_rows[chosen_idx], weights[chosen_idx]
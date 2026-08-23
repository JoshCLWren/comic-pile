"""Pure weight calculation and weighted selection for contextual rolls."""

import random
from typing import Any, Literal

PoolRow = tuple[Any, int, Any]
BandwidthMode = Literal["light", "balanced", "deep"]

VALID_BANDWIDTH_MODES = ("light", "balanced", "deep")
WEIGHT_MIN = 0.1
WEIGHT_NEUTRAL = 1.0
WEIGHT_CAP = 10.0


def calculate_weights(pool_rows: list[PoolRow], bandwidth: BandwidthMode) -> list[float]:
    """Compute per-candidate selection weights for the given bandwidth mode.

    Effort is proxied by the unread issue count carried in each pool row.
    Lower effort means fewer unread issues and less reading fatigue.

    Mode mapping (effort from 0 to unbounded, proxy = unread_count):

        light  - weight rises as effort falls; favors quick, low-effort reads.
        balanced - all candidates receive neutral weight regardless of effort.
        deep   - weight rises with effort up to the cap; promotes immersive
                 reading without ever excluding the lower-effort candidates.

    Weights are clamped to [WEIGHT_MIN, WEIGHT_CAP] so no single candidate
    can monopolize or zero-out the selection. Candidates sharing one effort
    level always receive equal weights, so uniform pools stay uniform in
    every bandwidth mode.

    Args:
        pool_rows: Pre-bounded candidate pool ordered by queue position.
        bandwidth: Reader bandwidth mode: "light", "balanced", or "deep".

    Returns:
        List of positive floats, one per pool_rows entry.

    Raises:
        ValueError: If pool_rows is empty or bandwidth is not a valid mode.
    """
    if not pool_rows:
        raise ValueError("pool_rows must contain at least one candidate")

    if bandwidth not in VALID_BANDWIDTH_MODES:
        raise ValueError(
            f"Unknown bandwidth mode '{bandwidth}'. Expected 'light', 'balanced', or 'deep'."
        )

    efforts = [row[1] or 0 for row in pool_rows]
    if len(set(efforts)) == 1:
        return [WEIGHT_NEUTRAL] * len(pool_rows)

    max_effort = max(efforts)

    def _compute_weight(effort: int) -> float:
        if bandwidth == "balanced":
            return WEIGHT_NEUTRAL
        normalized = min(effort / max_effort, 1.0)
        if bandwidth == "light":
            weight = 1.0 + 3.0 * (1.0 - normalized)
        else:
            weight = 0.5 + 0.5 * normalized * WEIGHT_CAP
        return max(WEIGHT_MIN, min(WEIGHT_CAP, weight))

    return [_compute_weight(effort) for effort in efforts]


def select_weighted(
    pool_rows: list[PoolRow],
    bandwidth: BandwidthMode,
    rng: random.Random | None = None,
) -> tuple[int, PoolRow, float]:
    """Choose one candidate from the bounded pool using weighted selection.

    Falls back to a uniform choice when every candidate carries an equal
    weight (including balanced mode and single-candidate pools) or when the
    computed weights are invalid, so selection never fails closed.

    Args:
        pool_rows: Pre-bounded candidate pool ordered by queue position.
        bandwidth: Reader bandwidth mode: "light", "balanced", or "deep".
        rng: Optional seeded ``random.Random`` for reproducible selection.
            Defaults to a fresh OS-entropy generator when None.

    Returns:
        Tuple of (selected_index, selected_pool_row, weight_at_selected_index).

    Raises:
        ValueError: If pool_rows is empty or bandwidth is invalid.
    """
    weights = calculate_weights(pool_rows, bandwidth)
    chooser = rng if rng is not None else random.Random()

    if len(pool_rows) == 1:
        return 0, pool_rows[0], weights[0]

    uniform = len({round(w, 6) for w in weights}) == 1
    if uniform or sum(weights) <= 0:
        idx = chooser.randint(0, len(pool_rows) - 1)
        return idx, pool_rows[idx], weights[idx]

    chosen_idx = chooser.choices(range(len(pool_rows)), weights=weights, k=1)[0]
    return chosen_idx, pool_rows[chosen_idx], weights[chosen_idx]

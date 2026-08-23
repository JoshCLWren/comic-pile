"""Tests for pure weight calculation and weighted selection."""

import random

import pytest

from comic_pile.roll_weights import (
    WEIGHT_CAP,
    WEIGHT_MIN,
    WEIGHT_NEUTRAL,
    calculate_weights,
    select_weighted,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rows(*efforts: int) -> list[tuple[object, int, object]]:
    """Build pool rows where position-1 carries the effort proxy (unread count)."""
    return [(object(), e, None) for e in efforts]


# ---------------------------------------------------------------------------
# calculate_weights
# ---------------------------------------------------------------------------


class TestCalculateWeights:
    def test_balanced_all_neutral(self) -> None:
        weights = calculate_weights(_rows(1, 3, 5), "balanced")
        assert weights == [WEIGHT_NEUTRAL, WEIGHT_NEUTRAL, WEIGHT_NEUTRAL]

    def test_balanced_single_candidate_weight_neutral(self) -> None:
        weights = calculate_weights(_rows(7), "balanced")
        assert weights == [WEIGHT_NEUTRAL]

    def test_light_favors_lower_effort(self) -> None:
        rows = _rows(0, 5, 10)
        weights = calculate_weights(rows, "light")
        assert weights[0] > weights[1] > weights[2]
        assert weights[2] >= WEIGHT_MIN

    def test_light_monotonic_decreasing(self) -> None:
        for effort in range(1, 11):
            w_low = calculate_weights(_rows(effort - 1), "light")[0]
            w_high = calculate_weights(_rows(effort), "light")[0]
            assert w_low > w_high

    def test_deep_favors_higher_effort(self) -> None:
        rows = _rows(0, 5, 10)
        weights = calculate_weights(rows, "deep")
        assert weights[0] < weights[1] < weights[2]
        assert weights[2] <= WEIGHT_CAP

    def test_deep_monotonic_increasing(self) -> None:
        for effort in range(1, 11):
            w_low = calculate_weights(_rows(effort - 1), "deep")[0]
            w_high = calculate_weights(_rows(effort), "deep")[0]
            assert w_low < w_high

    def test_deep_all_weights_positive(self) -> None:
        rows = _rows(0, 5, 10)
        weights = calculate_weights(rows, "deep")
        assert all(w > 0 for w in weights)
        min_w = min(weights)
        assert min_w >= WEIGHT_MIN

    def test_light_zero_effort_gets_highest_weight(self) -> None:
        rows = _rows(0, 1)
        weights = calculate_weights(rows, "light")
        assert weights[0] == max(weights)
        assert weights[0] > WEIGHT_NEUTRAL

    def test_deep_zero_effort_not_excluded(self) -> None:
        rows = _rows(0, 1)
        weights = calculate_weights(rows, "deep")
        assert weights[0] > 0
        assert weights[0] >= WEIGHT_MIN

    def test_all_equal_effort_balanced_neutral(self) -> None:
        weights = calculate_weights(_rows(3, 3, 3), "balanced")
        assert all(abs(w - WEIGHT_NEUTRAL) < 1e-9 for w in weights)

    def test_all_equal_effort_light_neutral(self) -> None:
        weights = calculate_weights(_rows(0, 0), "light")
        assert all(abs(w - WEIGHT_NEUTRAL) < 1e-9 for w in weights)

    def test_all_equal_effort_deep_neutral(self) -> None:
        weights = calculate_weights(_rows(5, 5), "deep")
        assert all(abs(w - WEIGHT_NEUTRAL) < 1e-9 for w in weights)

    def test_none_effort_treated_as_zero(self) -> None:
        rows = [(object(), 0, None), (object(), None, None)]
        weights_l = calculate_weights(rows, "light")
        weights_d = calculate_weights(rows, "deep")
        assert all(w >= WEIGHT_MIN for w in weights_l)
        assert all(w >= WEIGHT_MIN for w in weights_d)

    def test_upper_cap_not_exceeded(self) -> None:
        rows = _rows(0, 1000)
        for mode in ("light", "deep"):
            weights = calculate_weights(rows, mode)
            assert max(weights) <= WEIGHT_CAP

    def test_lower_floor_not_broken(self) -> None:
        rows = _rows(0, 1000)
        for mode in ("light", "deep"):
            weights = calculate_weights(rows, mode)
            assert all(w >= WEIGHT_MIN for w in weights)

    def test_empty_pool_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="at least one candidate"):
            calculate_weights([], "balanced")

    def test_invalid_bandwidth_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown bandwidth mode"):
            calculate_weights(_rows(1, 2), "speed")

    @pytest.mark.parametrize("mode", ["light", "balanced", "deep"])
    def test_output_length_matches_input(self, mode: str) -> None:
        for size in (1, 2, 5, 20):
            weights = calculate_weights(_rows(*range(size)), mode)
            assert len(weights) == size

    @pytest.mark.parametrize("mode", ["light", "balanced", "deep"])
    def test_all_weights_positive(self, mode: str) -> None:
        rows = _rows(0, 1, 5, 10, 50)
        weights = calculate_weights(rows, mode)
        assert all(w > 0 for w in weights)

    def test_balanced_mode_value_constant_across_efforts(self) -> None:
        rows = _rows(0, 1, 2, 5, 10, 50, 100)
        weights = calculate_weights(rows, "balanced")
        assert len(set(round(w, 9) for w in weights)) == 1


# ---------------------------------------------------------------------------
# select_weighted – deterministic seeded behavior
# ---------------------------------------------------------------------------


class TestSelectWeighted:
    def test_single_candidate_always_chosen(self) -> None:
        idx, row, weight = select_weighted(_rows(5), "light")
        assert idx == 0
        assert row[1] == 5
        assert weight >= WEIGHT_MIN

    def test_balanced_approximately_uniform(self) -> None:
        rows = _rows(0, 1, 2, 3, 4)
        rng = random.Random(42)
        picked = [select_weighted(rows, "balanced", rng=rng)[0] for _ in range(2000)]
        counts = {i: picked.count(i) for i in range(5)}
        expected = 400.0
        for count in counts.values():
            assert abs(count - expected) / expected < 0.15

    def test_light_favors_low_effort_statistically(self) -> None:
        rows = _rows(0, 1, 2, 3, 4)
        rng = random.Random(99)
        picks = [select_weighted(rows, "light", rng=rng)[0] for _ in range(4000)]
        zero_count = picks.count(0)
        max_effort_count = picks.count(4)
        assert zero_count > max_effort_count * 2, (
            f"light mode should significantly favor index 0 "
            f"(effort=0): got {zero_count} vs {max_effort_count} highest-effort picks"
        )

    def test_deep_mode_includes_low_effort(self) -> None:
        rows = _rows(0, 5, 10)
        rng = random.Random(77)
        picks = [select_weighted(rows, "deep", rng=rng)[0] for _ in range(2000)]
        assert picks.count(0) > 0, "deep mode must not exclude low-effort candidates"

    def test_no_candidate_outside_pool_chosen(self) -> None:
        pool = _rows(0, 2, 4)
        rng = random.Random(123)
        for _ in range(500):
            idx, _, _ = select_weighted(pool, "light", rng=rng)
            assert 0 <= idx < len(pool)

    def test_deterministic_with_same_seed(self) -> None:
        rows = _rows(1, 2, 3, 4, 5)
        rng1 = random.Random(42)
        rng2 = random.Random(42)
        result1 = select_weighted(rows, "light", rng=rng1)
        result2 = select_weighted(rows, "light", rng=rng2)
        assert result1[0] == result2[0], "same seed must produce identical selections"

    def test_same_seed_always_agrees(self) -> None:
        rows = _rows(1, 2, 3, 4, 5)
        all_agree = all(
            select_weighted(rows, "light", rng=random.Random(42))[0]
            == select_weighted(rows, "light", rng=random.Random(42))[0]
            for _ in range(200)
        )
        assert all_agree, "same seed must always produce the same selection"

    def test_result_returns_positive_weight(self) -> None:
        _, _, weight = select_weighted(_rows(3, 7, 1), "light")
        assert weight > 0

    def test_selected_index_always_in_range(self) -> None:
        rows = _rows(3, 7, 1)
        idx, _, _ = select_weighted(rows, "balanced")
        assert 0 <= idx < len(rows)

    def test_selected_row_matches_index(self) -> None:
        rows = _rows(2, 4, 6)
        idx, row, _ = select_weighted(rows, "balanced", rng=random.Random(0))
        assert rows[idx] is row

    def test_selected_effort_matches_row(self) -> None:
        rows = _rows(10, 20, 30)
        idx, row, _ = select_weighted(rows, "light", rng=random.Random(5))
        assert rows[idx][1] == row[1]

    @pytest.mark.parametrize("bad_mode", ["fast", "medium", "unknown", ""])
    def test_invalid_bandwidth_raises_value_error(self, bad_mode: str) -> None:
        with pytest.raises(ValueError, match="Unknown bandwidth mode"):
            select_weighted(_rows(1, 2), bad_mode)

    def test_empty_pool_raises_in_select_weighted(self) -> None:
        with pytest.raises(ValueError):
            select_weighted([], "balanced")
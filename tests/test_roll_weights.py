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


def _rows(*efforts: int) -> list[tuple[object, int, object]]:
    """Build pool rows where position-1 carries the effort proxy (unread count)."""
    return [(object(), e, None) for e in efforts]


class TestCalculateWeights:
    """Weight computation across bandwidth modes, boundaries, and caps."""

    def test_balanced_all_neutral(self) -> None:
        """Balanced mode gives every candidate the neutral weight."""
        weights = calculate_weights(_rows(1, 3, 5), "balanced")
        assert weights == [WEIGHT_NEUTRAL, WEIGHT_NEUTRAL, WEIGHT_NEUTRAL]

    def test_balanced_single_candidate_weight_neutral(self) -> None:
        """A single candidate in balanced mode receives the neutral weight."""
        weights = calculate_weights(_rows(7), "balanced")
        assert weights == [WEIGHT_NEUTRAL]

    def test_light_favors_lower_effort(self) -> None:
        """Light mode assigns strictly higher weights to lower-effort rows."""
        rows = _rows(0, 5, 10)
        weights = calculate_weights(rows, "light")
        assert weights[0] > weights[1] > weights[2]
        assert weights[2] >= WEIGHT_MIN

    def test_light_monotonic_decreasing(self) -> None:
        """Light mode weight decreases monotonically as effort rises."""
        rows = _rows(*range(11))
        weights = calculate_weights(rows, "light")
        assert all(a > b for a, b in zip(weights, weights[1:], strict=False))

    def test_deep_favors_higher_effort(self) -> None:
        """Deep mode assigns strictly higher weights to higher-effort rows."""
        rows = _rows(0, 5, 10)
        weights = calculate_weights(rows, "deep")
        assert weights[0] < weights[1] < weights[2]
        assert weights[2] <= WEIGHT_CAP

    def test_deep_monotonic_increasing(self) -> None:
        """Deep mode weight increases monotonically as effort rises."""
        rows = _rows(*range(11))
        weights = calculate_weights(rows, "deep")
        assert all(a < b for a, b in zip(weights, weights[1:], strict=False))

    def test_deep_all_weights_positive(self) -> None:
        """Deep mode never produces a zero or negative weight."""
        rows = _rows(0, 5, 10)
        weights = calculate_weights(rows, "deep")
        assert all(w > 0 for w in weights)
        min_w = min(weights)
        assert min_w >= WEIGHT_MIN

    def test_light_zero_effort_gets_highest_weight(self) -> None:
        """The zero-effort candidate carries the top weight in light mode."""
        rows = _rows(0, 1)
        weights = calculate_weights(rows, "light")
        assert weights[0] == max(weights)
        assert weights[0] > WEIGHT_NEUTRAL

    def test_deep_zero_effort_not_excluded(self) -> None:
        """Deep mode keeps zero-effort candidates selectable."""
        rows = _rows(0, 1)
        weights = calculate_weights(rows, "deep")
        assert weights[0] > 0
        assert weights[0] >= WEIGHT_MIN

    def test_all_equal_effort_balanced_neutral(self) -> None:
        """Equal candidates stay neutral-weighted in balanced mode."""
        weights = calculate_weights(_rows(3, 3, 3), "balanced")
        assert all(abs(w - WEIGHT_NEUTRAL) < 1e-9 for w in weights)

    def test_all_equal_effort_light_neutral(self) -> None:
        """Equal candidates receive equal neutral weights in light mode."""
        weights = calculate_weights(_rows(0, 0), "light")
        assert all(abs(w - WEIGHT_NEUTRAL) < 1e-9 for w in weights)

    def test_all_equal_effort_deep_neutral(self) -> None:
        """Equal candidates receive equal neutral weights in deep mode."""
        weights = calculate_weights(_rows(5, 5), "deep")
        assert all(abs(w - WEIGHT_NEUTRAL) < 1e-9 for w in weights)

    def test_none_effort_treated_as_zero(self) -> None:
        """Unknown effort is clamped into range instead of crashing either mode."""
        rows = [(object(), 0, None), (object(), None, None)]
        weights_l = calculate_weights(rows, "light")
        weights_d = calculate_weights(rows, "deep")
        assert all(w >= WEIGHT_MIN for w in weights_l)
        assert all(w >= WEIGHT_MIN for w in weights_d)

    def test_upper_cap_not_exceeded(self) -> None:
        """No mode exceeds WEIGHT_CAP even with extreme effort spread."""
        rows = _rows(0, 1000)
        for mode in ("light", "deep"):
            weights = calculate_weights(rows, mode)
            assert max(weights) <= WEIGHT_CAP

    def test_lower_floor_not_broken(self) -> None:
        """No mode drops below WEIGHT_MIN even with extreme effort spread."""
        rows = _rows(0, 1000)
        for mode in ("light", "deep"):
            weights = calculate_weights(rows, mode)
            assert all(w >= WEIGHT_MIN for w in weights)

    def test_empty_pool_raises_value_error(self) -> None:
        """An empty candidate pool is rejected explicitly."""
        with pytest.raises(ValueError, match="at least one candidate"):
            calculate_weights([], "balanced")

    def test_invalid_bandwidth_raises_value_error(self) -> None:
        """An unknown bandwidth mode is rejected explicitly."""
        with pytest.raises(ValueError, match="Unknown bandwidth mode"):
            calculate_weights(_rows(1, 2), "speed")

    @pytest.mark.parametrize("mode", ["light", "balanced", "deep"])
    def test_output_length_matches_input(self, mode: str) -> None:
        """One weight is returned per candidate for every pool size."""
        for size in (1, 2, 5, 20):
            weights = calculate_weights(_rows(*range(size)), mode)
            assert len(weights) == size

    @pytest.mark.parametrize("mode", ["light", "balanced", "deep"])
    def test_all_weights_positive(self, mode: str) -> None:
        """Every computed weight stays positive in every mode."""
        rows = _rows(0, 1, 5, 10, 50)
        weights = calculate_weights(rows, mode)
        assert all(w > 0 for w in weights)

    def test_balanced_mode_value_constant_across_efforts(self) -> None:
        """Balanced mode ignores effort spread entirely."""
        rows = _rows(0, 1, 2, 5, 10, 50, 100)
        weights = calculate_weights(rows, "balanced")
        assert len({round(w, 9) for w in weights}) == 1


class TestSelectWeighted:
    """Seeded deterministic behavior of weighted selection."""

    def test_single_candidate_always_chosen(self) -> None:
        """A one-candidate pool always selects that candidate."""
        idx, row, weight = select_weighted(_rows(5), "light")
        assert idx == 0
        assert row[1] == 5
        assert weight >= WEIGHT_MIN

    def test_balanced_approximately_uniform(self) -> None:
        """Balanced selection is statistically uniform across candidates."""
        rows = _rows(0, 1, 2, 3, 4)
        rng = random.Random(42)
        picked = [select_weighted(rows, "balanced", rng=rng)[0] for _ in range(2000)]
        counts = {i: picked.count(i) for i in range(5)}
        expected = 400.0
        for count in counts.values():
            assert abs(count - expected) / expected < 0.15

    def test_light_favors_low_effort_statistically(self) -> None:
        """Light mode picks low-effort candidates far more often."""
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
        """Deep mode still selects low-effort candidates sometimes."""
        rows = _rows(0, 5, 10)
        rng = random.Random(77)
        picks = [select_weighted(rows, "deep", rng=rng)[0] for _ in range(2000)]
        assert picks.count(0) > 0, "deep mode must not exclude low-effort candidates"

    def test_no_candidate_outside_pool_chosen(self) -> None:
        """Selection indices never escape the bounded pool."""
        pool = _rows(0, 2, 4)
        rng = random.Random(123)
        for _ in range(500):
            idx, _, _ = select_weighted(pool, "light", rng=rng)
            assert 0 <= idx < len(pool)

    def test_deterministic_with_same_seed(self) -> None:
        """Two generators sharing a seed agree on the first selection."""
        rows = _rows(1, 2, 3, 4, 5)
        rng1 = random.Random(42)
        rng2 = random.Random(42)
        result1 = select_weighted(rows, "light", rng=rng1)
        result2 = select_weighted(rows, "light", rng=rng2)
        assert result1[0] == result2[0], "same seed must produce identical selections"

    def test_same_seed_always_agrees(self) -> None:
        """Repeated fresh seeds reproduce identical selections."""
        rows = _rows(1, 2, 3, 4, 5)
        all_agree = all(
            select_weighted(rows, "light", rng=random.Random(42))[0]
            == select_weighted(rows, "light", rng=random.Random(42))[0]
            for _ in range(200)
        )
        assert all_agree, "same seed must always produce the same selection"

    def test_result_returns_positive_weight(self) -> None:
        """The reported weight for the chosen candidate is positive."""
        _, _, weight = select_weighted(_rows(3, 7, 1), "light")
        assert weight > 0

    def test_selected_index_always_in_range(self) -> None:
        """A default-generator selection stays inside the pool."""
        rows = _rows(3, 7, 1)
        idx, _, _ = select_weighted(rows, "balanced")
        assert 0 <= idx < len(rows)

    def test_selected_row_matches_index(self) -> None:
        """The returned row object matches the selected index."""
        rows = _rows(2, 4, 6)
        idx, row, _ = select_weighted(rows, "balanced", rng=random.Random(0))
        assert rows[idx] is row

    def test_selected_effort_matches_row(self) -> None:
        """The selected row's effort matches its index position."""
        rows = _rows(10, 20, 30)
        idx, row, _ = select_weighted(rows, "light", rng=random.Random(5))
        assert rows[idx][1] == row[1]

    @pytest.mark.parametrize("bad_mode", ["fast", "medium", "unknown", ""])
    def test_invalid_bandwidth_raises_value_error(self, bad_mode: str) -> None:
        """Selection rejects unknown bandwidth modes explicitly."""
        with pytest.raises(ValueError, match="Unknown bandwidth mode"):
            select_weighted(_rows(1, 2), bad_mode)

    def test_empty_pool_raises_in_select_weighted(self) -> None:
        """Selection rejects an empty candidate pool explicitly."""
        with pytest.raises(ValueError):
            select_weighted([], "balanced")

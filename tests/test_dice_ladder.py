"""Tests for dice ladder logic."""


from comic_pile.dice_ladder import DICE_LADDER, step_down, step_down_to_min, step_up, step_up_to_max


def test_step_down():
    """Verify dice steps down (d10 -> d8, d8 -> d6)."""
    assert step_down(10) == 8
    assert step_down(8) == 6
    assert step_down(12) == 10


def test_step_up():
    """Verify dice steps up (d6 -> d8, d8 -> d10)."""
    assert step_up(6) == 8
    assert step_up(8) == 10
    assert step_up(10) == 12


def test_step_down_bounds():
    """Returns same when at d4 (minimum)."""
    assert step_down(4) == 4


def test_step_up_bounds():
    """Returns same when at d20 (maximum)."""
    assert step_up(20) == 20


def test_step_up_to_max():
    """Steps all the way to d20."""
    assert step_up_to_max(4) == 20
    assert step_up_to_max(6) == 20
    assert step_up_to_max(10) == 20
    assert step_up_to_max(20) == 20


def test_step_down_to_min():
    """Steps all the way to d4."""
    assert step_down_to_min(20) == 4
    assert step_down_to_min(12) == 4
    assert step_down_to_min(8) == 4
    assert step_down_to_min(4) == 4


def test_full_ladder_traversal():
    """Test step through all dice values."""
    result = step_up(4)
    for expected in [6, 8, 10, 12, 20]:
        assert result == expected
        result = step_up(result)

    assert step_up(20) == 20

    result = step_down(20)
    for expected in [12, 10, 8, 6, 4]:
        assert result == expected
        result = step_down(result)

    assert step_down(4) == 4


def test_invalid_die_size_step_down():
    """Returns same die size for invalid values."""
    assert step_down(5) == 5
    assert step_down(100) == 100
    assert step_down(3) == 3


def test_invalid_die_size_step_up():
    """Returns same die size for invalid values."""
    assert step_up(5) == 5
    assert step_up(100) == 100
    assert step_up(3) == 3


def test_dice_ladder_constant():
    """Verify DICE_LADDER contains expected values."""
    assert DICE_LADDER == [4, 6, 8, 10, 12, 20]
    assert len(DICE_LADDER) == 6
    assert DICE_LADDER[0] == 4
    assert DICE_LADDER[-1] == 20

"""Dice ladder logic for managing die size progression."""

DICE_LADDER = [4, 6, 8, 10, 12, 20]


def step_down(die_size: int) -> int:
    """Move down one step on the dice ladder.

    Args:
        die_size: Current die size.

    Returns:
        Next smaller die size, or current if already at minimum.
    """
    if die_size not in DICE_LADDER:
        raise ValueError(f"Invalid die size: {die_size}. Valid sizes: {DICE_LADDER}")

    try:
        index = DICE_LADDER.index(die_size)
        if index > 0:
            return DICE_LADDER[index - 1]
        return die_size
    except ValueError:
        return die_size


def step_up(die_size: int) -> int:
    """Move up one step on the dice ladder.

    Args:
        die_size: Current die size.

    Returns:
        Next larger die size, or current if already at maximum.
    """
    if die_size not in DICE_LADDER:
        raise ValueError(f"Invalid die size: {die_size}. Valid sizes: {DICE_LADDER}")

    try:
        index = DICE_LADDER.index(die_size)
        if index < len(DICE_LADDER) - 1:
            return DICE_LADDER[index + 1]
        return die_size
    except ValueError:
        return die_size

def test_step_up_enforces_bounds():
    """Test that step_up enforces valid die sizes."""
    import pytest
    
    # Valid die sizes
    valid_sizes = [4, 6, 8, 10, 12, 20]
    
    # Test each step function
    for i, expected in enumerate(valid_sizes):
        result = step_up(i)
        assert result == expected, f"step_up({i}) should return {expected}, got {result}"
        
    # Test invalid die sizes
    invalid_sizes = [1, 2, 3, 5, 7, 9, 11, 13, 14, 15, 16, 17, 18, 19]
    for invalid_size in invalid_sizes:
        with pytest.raises(ValueError, match=fr"Invalid die size: {invalid_size}"):
            step_up(invalid_size)

def test_step_down_enforces_bounds():
    """Test that step_down enforces valid die sizes."""
    import pytest
    
    # Valid die sizes
    valid_sizes = [4, 6, 8, 10, 12, 20]
    
    # Test each step function
    for i, expected in enumerate(valid_sizes):
        result = step_up(i)
        assert result == expected, f"step_up({i}) should return {expected}, got {result}"
        
    # Test invalid die sizes
    invalid_sizes = [1, 2, 3, 5, 7, 9, 11, 13, 14, 15, 16, 17, 18, 19]
    for invalid_size in invalid_sizes:
        with pytest.raises(ValueError, match=fr"Invalid die size: {invalid_size}"):
            step_down(invalid_size)

def test_invalid_die_size_step_down():
    """Returns same die size for invalid values."""
    # Test that step_down rejects invalid die sizes by returning them unchanged
    assert step_down(5) == 5

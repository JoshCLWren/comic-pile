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

    index = DICE_LADDER.index(die_size)
    if index > 0:
        return DICE_LADDER[index - 1]
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

    index = DICE_LADDER.index(die_size)
    if index < len(DICE_LADDER) - 1:
        return DICE_LADDER[index + 1]
    return die_size

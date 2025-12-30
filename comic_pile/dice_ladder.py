"""Dice ladder logic for managing die size progression."""

DICE_LADDER = [4, 6, 8, 10, 12, 20]


def step_down(die_size: int) -> int:
    """Move down one step on the dice ladder.

    Args:
        die_size: Current die size.

    Returns:
        Next smaller die size, or current if already at minimum.
    """
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
    try:
        index = DICE_LADDER.index(die_size)
        if index < len(DICE_LADDER) - 1:
            return DICE_LADDER[index + 1]
        return die_size
    except ValueError:
        return die_size


def step_up_to_max(die_size: int) -> int:
    """Step up all the way to d20.

    Args:
        die_size: Current die size.

    Returns:
        d20 always.
    """
    return DICE_LADDER[-1]


def step_down_to_min(die_size: int) -> int:
    """Step down all the way to d4.

    Args:
        die_size: Current die size.

    Returns:
        d4 always.
    """
    return DICE_LADDER[0]

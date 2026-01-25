"""Dice ladder logic for managing die size progression.

The Dice Ladder System
======================
The dice ladder is the core game mechanic that governs how comics are selected
for reading. It uses standard RPG polyhedral dice (d4, d6, d8, d10, d12, d20)
to create a dynamic selection pool that responds to reading satisfaction.

How It Works:
-------------
1. The current die determines the pool size (e.g., d6 = top 6 comics in queue)
2. When rolling, a random comic from positions 1 to die_size is selected
3. After rating a reading session:
   - Rating >= threshold (default 4.0): Die steps DOWN (smaller pool = more focused)
   - Rating < threshold: Die steps UP (larger pool = more variety)

Design Philosophy:
------------------
- Good experiences (high ratings) narrow the pool to keep you in a "flow state"
  with comics you're enjoying, reducing decision fatigue
- Poor experiences (low ratings) expand the pool to introduce variety and help
  discover better-fitting comics
- The ladder creates natural feedback loops that adapt to reading patterns

Ladder Progression:
-------------------
    d4 <-> d6 <-> d8 <-> d10 <-> d12 <-> d20
    ^                                      ^
    (minimum - tight focus)     (maximum - wide variety)

Example Flow:
-------------
1. Start at d6 (6 comics in pool)
2. Rate highly -> step down to d4 (4 comics)
3. Rate poorly -> step up to d6 (6 comics)
4. Continue rating poorly -> step up to d8, d10, etc.
"""

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

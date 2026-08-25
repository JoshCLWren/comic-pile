"""Shared insertion and anchor arithmetic for reading order items.

Used by both the generic reading-order insert endpoint and the ComicVine
import flow so that position shifting behaves identically everywhere.
"""

from __future__ import annotations

from app.models.reading_order import ReadingOrderItem


def resolve_anchored_position(
    positions_by_thread: dict[int, int],
    anchor_before_thread_id: int | None,
    anchor_after_thread_id: int | None,
    total_items: int,
) -> int:
    """Resolve the 1-based insertion position between two neighbor anchors.

    The anchors are the thread IDs of the arc members immediately preceding and
    following the imported issue in story-arc order. Resolution rules, applied
    in order:

    - Both anchors present and ordered (``before`` earlier than ``after``):
      insert directly before ``after``, which lands strictly between them.
    - Only the preceding member present: insert directly after it.
    - Only the following member present: insert directly before it.
    - Both present but contradictorily ordered (the user's custom order runs
      opposite to arc sequence): keep adjacency to the preceding member.
    - No usable anchor: append at the end of the reading order.

    Args:
        positions_by_thread: Mapping of thread ID to current 1-based position
            for every item already in the target reading order. Anchors that
            are absent from this mapping (other users' threads, threads not in
            this order) are treated as unusable.
        anchor_before_thread_id: Thread ID of the preceding arc member, if any.
        anchor_after_thread_id: Thread ID of the following arc member, if any.
        total_items: Current number of items in the reading order.

    Returns:
        The resolved 1-based insertion position.
    """
    before_pos = (
        positions_by_thread.get(anchor_before_thread_id)
        if anchor_before_thread_id is not None
        else None
    )
    after_pos = (
        positions_by_thread.get(anchor_after_thread_id)
        if anchor_after_thread_id is not None
        else None
    )
    if before_pos is not None and after_pos is not None and before_pos < after_pos:
        return after_pos
    if before_pos is not None:
        return before_pos + 1
    if after_pos is not None:
        return after_pos
    return total_items + 1


def apply_insert(
    items: list[ReadingOrderItem],
    thread_id: int,
    target_pos: int,
) -> None:
    """Make room at ``target_pos`` for ``thread_id`` by shifting positions.

    If the thread already belongs to the list it is moved instead of being
    duplicated; otherwise every existing item at or after ``target_pos`` is
    shifted one slot later. Mutates ``items`` in place.

    Args:
        items: All items of the reading order in any order; positions are read
            and written on the objects themselves.
        thread_id: Thread being inserted or moved.
        target_pos: Desired 1-based position after the operation.
    """
    current_item = next((item for item in items if item.thread_id == thread_id), None)

    if current_item is not None:
        old_pos = current_item.position
        if old_pos < target_pos:
            for item in items:
                if old_pos < item.position <= target_pos:
                    item.position -= 1
        elif target_pos < old_pos:
            for item in items:
                if target_pos <= item.position < old_pos:
                    item.position += 1
        current_item.position = target_pos
        return

    for item in items:
        if item.position >= target_pos:
            item.position += 1

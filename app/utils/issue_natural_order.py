"""Natural placement helpers for thread-local issue order.

``Issue.position`` is the single canonical thread order shared by Edit Series,
Queue, Roll, and thread progression. When a reader adds ordinary numeric issue
numbers to an existing series, those issues belong at their natural position
rather than at the end of the series.

Automatic placement is only applied to ordinary positive issue numbers.
When existing annuals, specials, decimals, or other irregular labels already
have saved positions, insert new numeric issues around them without moving
those saved issues relative to one another. Return ``None`` for an ambiguous
number-only anchor (no regular issues or out-of-order regular issues).

Ordinary numeric series are seated from the set of numbers, even when an
earlier append left the thread out of ascending order. Roll then follows
that same ``Issue.position`` series progression plus explicitly recorded
checkpoints; this helper does not invent a second ordering system or
dependency edges.

This module is pure so both the placement decision and its tests stay free of
database and request concerns.
"""

import re
from collections.abc import Sequence

# Ordinary issue numbers are canonical unsigned decimals without a leading zero.
# "0", "007", "1.5", "Annual 1", "1-Annual", and "-1" all fail this pattern
# because their position inside a series is a publisher/reader decision.
ORDINARY_ISSUE_NUMBER = re.compile(r"^[1-9][0-9]*$")


def parse_ordinary_issue_number(issue_number: str) -> int | None:
    """Return the natural sort value of an ordinary issue number.

    Args:
        issue_number: Issue identifier as stored on ``Issue.issue_number``.

    Returns:
        The positive integer value, or ``None`` when the identifier is not an
        ordinary number and therefore has no unambiguous natural position.
    """
    if not ORDINARY_ISSUE_NUMBER.match(issue_number):
        return None

    return int(issue_number)


def natural_issue_order(
    existing_issue_numbers: Sequence[str],
    new_issue_numbers: Sequence[str],
) -> list[str] | None:
    """Merge new issue numbers into a series' natural order.

    For all-numeric threads, existing append mistakes are corrected by sorting.
    For mixed threads, existing issue placement is authoritative: new numeric
    issues are seated by their neighboring numbered issues, without moving
    annuals, specials, or any other already saved issue. Incoming irregular
    labels and mixed threads with ambiguous numeric anchors keep the manual
    insertion fallback.

    Args:
        existing_issue_numbers: Issue numbers already in the thread, in canonical
            ``Issue.position`` order.
        new_issue_numbers: Issue numbers about to be created, already filtered
            against the existing numbers.

    Returns:
        Every issue number of the resulting thread in ascending natural order,
        or ``None`` when automatic placement would be ambiguous and the existing
        canonical order must be preserved instead.
    """
    incoming: list[tuple[int, str]] = []
    for issue_number in new_issue_numbers:
        value = parse_ordinary_issue_number(issue_number)
        if value is None:
            return None
        incoming.append((value, issue_number))

    existing_numbered = [
        (value, issue_number)
        for issue_number in existing_issue_numbers
        if (value := parse_ordinary_issue_number(issue_number)) is not None
    ]

    # The all-numeric case still repairs previous out-of-order appends
    # (including the Ultimate X-Men #1–#24 recovery in #3483).
    if len(existing_numbered) == len(existing_issue_numbers):
        return [
            label
            for _number, label in sorted([*existing_numbered, *incoming])
        ]

    # Mixed threads contain reader-placed annuals, specials, and other
    # nonstandard labels. Never reorder their existing issue sequence.
    # A new ordinary number can be inserted relative to existing numbered
    # issues only if those numbers are already monotonically increasing.
    if not existing_numbered:
        return None
    numbers = [number for number, _label in existing_numbered]
    if numbers != sorted(numbers):
        return None

    result = list(existing_issue_numbers)
    for number, label in sorted(incoming):
        for index, existing_label in enumerate(result):
            existing_number = parse_ordinary_issue_number(existing_label)
            if existing_number is not None and existing_number > number:
                result.insert(index, label)
                break
        else:
            result.append(label)
    return result

"""Natural placement helpers for thread-local issue order.

``Issue.position`` is the single canonical thread order shared by Edit Series,
Queue, Roll, and thread progression. When a reader adds ordinary numeric issue
numbers to an existing series, those issues belong at their natural position
rather than at the end of the series.

Automatic placement is only applied when it is unambiguous: every number
involved must be an ordinary positive integer, and the series must already read
in ascending numeric order. Annuals, decimals and fractions, named specials,
``0``, padded numbers such as ``007``, and any series the reader reordered by
hand keep their existing canonical order so the reader can correct them
explicitly through the thread reorder path instead.

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

    The result depends only on the set of numbers, so the order they were typed
    in never changes the saved thread order.

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
    ordered_numbers: list[tuple[int, str]] = []
    previous_value: int | None = None

    for issue_number in existing_issue_numbers:
        value = parse_ordinary_issue_number(issue_number)
        if value is None:
            return None

        # A series that does not already read in ascending numeric order has
        # been ordered deliberately, so it must not be re-sorted behind the
        # reader's back.
        if previous_value is not None and value <= previous_value:
            return None

        previous_value = value
        ordered_numbers.append((value, issue_number))

    for issue_number in new_issue_numbers:
        value = parse_ordinary_issue_number(issue_number)
        if value is None:
            return None

        ordered_numbers.append((value, issue_number))

    ordered_numbers.sort(key=lambda entry: entry[0])

    return [issue_number for _value, issue_number in ordered_numbers]

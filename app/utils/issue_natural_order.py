"""Natural placement helpers for thread-local issue order.

``Issue.position`` is the single canonical thread order shared by Edit Series,
Queue, Roll, and thread progression. When a reader adds ordinary numeric issue
numbers to an existing series, those issues belong at their natural position
rather than at the end of the series.

Automatic placement is only applied when it is unambiguous: every number
involved must be an ordinary positive integer. Annuals, decimals and
fractions, named specials, ``0``, and padded numbers such as ``007`` keep
their existing canonical order so the reader can correct them explicitly
through the thread reorder path instead.

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

    The result depends only on the set of numbers, so the order they were typed
    in never changes the saved thread order. Existing position order is ignored
    for ordinary numbers so a previous append cannot force later inserts to the
    end of the thread.

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

    for issue_number in existing_issue_numbers:
        value = parse_ordinary_issue_number(issue_number)
        if value is None:
            return None
        ordered_numbers.append((value, issue_number))

    for issue_number in new_issue_numbers:
        value = parse_ordinary_issue_number(issue_number)
        if value is None:
            return None
        ordered_numbers.append((value, issue_number))

    ordered_numbers.sort(key=lambda entry: entry[0])

    return [issue_number for _value, issue_number in ordered_numbers]

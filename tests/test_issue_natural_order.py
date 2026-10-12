"""Unit tests for ordinary numeric natural-order placement (#3483)."""

from app.utils.issue_natural_order import natural_issue_order, parse_ordinary_issue_number


def test_parse_ordinary_issue_number_rejects_irregular_labels() -> None:
    """Annuals, decimals, zero, and padded numbers have no natural slot."""
    assert parse_ordinary_issue_number("12") == 12
    assert parse_ordinary_issue_number("0") is None
    assert parse_ordinary_issue_number("007") is None
    assert parse_ordinary_issue_number("1.5") is None
    assert parse_ordinary_issue_number("Annual 1") is None


def test_natural_issue_order_inserts_early_number_into_sorted_series() -> None:
    """Adding #1 to #7–#24 returns the full ascending series."""
    existing = [str(number) for number in range(7, 25)]
    assert natural_issue_order(existing, ["1"]) == ["1", *existing]


def test_natural_issue_order_reseats_already_appended_series() -> None:
    """A previous append of #2–#6 after #7–#24 still places #1 first (#3483)."""
    existing = [str(number) for number in range(7, 25)] + [str(number) for number in range(2, 7)]
    assert natural_issue_order(existing, ["1"]) == [str(number) for number in range(1, 25)]


def test_natural_issue_order_is_independent_of_input_order() -> None:
    """Typed order never changes the saved natural order."""
    existing = ["7", "8", "9"]
    assert natural_issue_order(existing, ["2", "1"]) == ["1", "2", "7", "8", "9"]
    assert natural_issue_order(existing, ["1", "2"]) == ["1", "2", "7", "8", "9"]


def test_natural_issue_order_returns_none_for_irregular_existing_or_new() -> None:
    """Irregular numbers stay on the append-only fallback."""
    assert natural_issue_order(["1", "Annual 1"], ["2"]) is None
    assert natural_issue_order(["1", "2"], ["1.5"]) is None

"""Test issue range parser functionality."""

import pytest

from app.utils.issue_parser import get_total_from_range, parse_issue_ranges


def test_parse_issue_ranges_simple():
    """Test parsing simple range."""
    result = parse_issue_ranges("1-25")
    assert result == [str(i) for i in range(1, 26)]
    assert len(result) == 25


def test_parse_issue_ranges_complex():
    """Test parsing complex range with commas and ranges."""
    result = parse_issue_ranges("1, 3, 5-7")
    assert result == ["1", "3", "5", "6", "7"]


def test_parse_issue_ranges_single():
    """Test parsing single issue."""
    result = parse_issue_ranges("5")
    assert result == ["5"]


def test_parse_issue_ranges_duplicates_removed():
    """Test that duplicates are removed."""
    result = parse_issue_ranges("1, 2, 2, 3, 3, 3")
    assert result == ["1", "2", "3"]


def test_parse_issue_ranges_empty_input():
    """Test that empty input raises error."""
    with pytest.raises(ValueError, match="Issue range cannot be empty"):
        parse_issue_ranges("")

    with pytest.raises(ValueError, match="Issue range cannot be empty"):
        parse_issue_ranges("   ")


def test_parse_issue_ranges_accepts_literals():
    """Test that non-numeric identifiers are accepted as literals."""
    result = parse_issue_ranges("Annual 1-5")
    assert result == ["Annual 1-5"]

    result = parse_issue_ranges("Special 1")
    assert result == ["Special 1"]

    result = parse_issue_ranges("0, 1-18, Annual 1")
    assert result == [str(i) for i in range(0, 19)] + ["Annual 1"]

    result = parse_issue_ranges("½")
    assert result == ["½"]


def test_parse_issue_ranges_invalid_format():
    """Test invalid range formats."""
    # "1-5-10": split("-", 1) → ["1", "5-10"], int("5-10") fails → stored as literal
    result = parse_issue_ranges("1-5-10")
    assert result == ["1-5-10"]

    # Non-numeric single token — accepted as literal identifier
    result = parse_issue_ranges("abc")
    assert result == ["abc"]

    # Negative (dash with empty left side) — stored as literal
    result = parse_issue_ranges("-5")
    assert result == ["-5"]

    # Range start > end
    with pytest.raises(ValueError, match="Range start.*cannot exceed end"):
        parse_issue_ranges("10-5")


def test_get_total_from_range():
    """Test getting total count from range."""
    assert get_total_from_range("1-25") == 25
    assert get_total_from_range("1, 3, 5-7") == 5
    assert get_total_from_range("5") == 1


def test_parse_issue_ranges_with_spaces():
    """Test parsing with various spacing."""
    result = parse_issue_ranges("1 - 5, 7 , 9-10")
    assert result == ["1", "2", "3", "4", "5", "7", "9", "10"]


def test_parse_issue_ranges_out_of_order():
    """Test parsing when issues are out of order."""
    result = parse_issue_ranges("5-7, 1-3")
    assert result == ["5", "6", "7", "1", "2", "3"]


def test_parse_issue_ranges_zero_accepted():
    """Test that zero is accepted as a valid issue number."""
    result = parse_issue_ranges("0")
    assert result == ["0"]

    result = parse_issue_ranges("0-5")
    assert result == ["0", "1", "2", "3", "4", "5"]


def test_parse_issue_ranges_large_numbers():
    """Test parsing large issue numbers."""
    result = parse_issue_ranges("999-1001")
    assert result == ["999", "1000", "1001"]
    assert len(result) == 3


def test_parse_issue_ranges_single_digit_ranges():
    """Test parsing single-digit ranges."""
    result = parse_issue_ranges("1-9")
    assert result == ["1", "2", "3", "4", "5", "6", "7", "8", "9"]
    assert len(result) == 9


def test_parse_issue_ranges_multiple_commas():
    """Test parsing with multiple consecutive commas."""
    result = parse_issue_ranges("1, 2, , 3")
    assert result == ["1", "2", "3"]


def test_parse_issue_ranges_trailing_comma():
    """Test parsing with trailing comma."""
    result = parse_issue_ranges("1, 2, 3,")
    assert result == ["1", "2", "3"]


def test_parse_issue_ranges_leading_comma():
    """Test parsing with leading comma."""
    result = parse_issue_ranges(", 1, 2, 3")
    assert result == ["1", "2", "3"]


def test_get_total_from_range_validates_input():
    """Test that get_total_from_range also validates input."""
    with pytest.raises(ValueError, match="Issue range cannot be empty"):
        get_total_from_range("")

    # Non-numeric literals are now accepted
    assert get_total_from_range("Annual 1") == 1


def test_parse_issue_ranges_preserves_string_format():
    """Test that issue numbers are returned as strings."""
    result = parse_issue_ranges("1-5")
    assert all(isinstance(issue, str) for issue in result)
    assert result == ["1", "2", "3", "4", "5"]


def test_parse_issue_ranges_range_edge_case():
    """Test parsing range with start equal to end."""
    result = parse_issue_ranges("5-5")
    assert result == ["5"]
    assert len(result) == 1


def test_parse_issue_ranges_mixed_single_and_range():
    """Test parsing mix of single issues and ranges."""
    result = parse_issue_ranges("1, 3-5, 7, 9-11")
    assert result == ["1", "3", "4", "5", "7", "9", "10", "11"]
    assert len(result) == 8

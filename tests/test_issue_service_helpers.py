"""Tests for issue service helper functions."""

import pytest

from app.services.issue import _compute_auto_insert_position, _is_simple_positive_integer


class TestIsSimplePositiveInteger:
    """Tests for _is_simple_positive_integer helper."""

    @pytest.mark.parametrize(
        "issue_number,expected",
        [
            ("1", True),
            ("2", True),
            ("10", True),
            ("99", True),
            ("100", True),
            ("999", True),
            ("0", False),
            ("-1", False),
            ("-10", False),
            ("½", False),
            ("1.5", False),
            ("1,5", False),
            ("Annual 1", False),
            ("Special", False),
            ("Issue 1", False),
            ("1a", False),
            ("01", False),  # Leading zero not allowed
            ("001", False),
            ("", False),
            (" ", False),
        ],
    )
    def test_is_simple_positive_integer(self, issue_number: str, expected: bool) -> None:
        """Test _is_simple_positive_integer with various inputs.

        Args:
            issue_number: The string to test.
            expected: The expected result (True for simple positive integer, False otherwise).
        """
        assert _is_simple_positive_integer(issue_number) == expected


class TestComputeAutoInsertPosition:
    """Tests for _compute_auto_insert_position helper."""

    def test_empty_existing_returns_zero(self) -> None:
        """No existing numeric issues -> insert at position 0 (beginning)."""
        existing_rows: list[tuple[int, str, int]] = []
        new_issues = ["1", "2", "3"]
        assert _compute_auto_insert_position(existing_rows, new_issues) == 0

    def test_insert_before_first_numeric(self) -> None:
        """New issues smaller than all existing -> insert at beginning."""
        existing_rows = [
            (1, "10", 1),
            (2, "20", 2),
            (3, "30", 3),
        ]
        new_issues = ["1", "2", "3"]
        # Should insert before position 1 (the first numeric issue)
        assert _compute_auto_insert_position(existing_rows, new_issues) == 0

    def test_insert_between_numeric(self) -> None:
        """New issues between existing numeric issues."""
        existing_rows = [
            (1, "10", 1),
            (2, "20", 2),
            (3, "30", 3),
        ]
        new_issues = ["15"]
        # 15 is between 10 and 20, should insert before position 2
        assert _compute_auto_insert_position(existing_rows, new_issues) == 1

    def test_insert_after_last_numeric(self) -> None:
        """New issues larger than all existing numeric -> append after last numeric."""
        existing_rows = [
            (1, "1", 1),
            (2, "2", 2),
            (3, "3", 3),
        ]
        new_issues = ["10", "11"]
        # Should insert after position 3 (last numeric)
        assert _compute_auto_insert_position(existing_rows, new_issues) == 3

    def test_ignores_non_numeric_existing(self) -> None:
        """Non-numeric existing issues are ignored for positioning."""
        existing_rows = [
            (1, "10", 1),
            (2, "Annual 1", 2),
            (3, "20", 3),
        ]
        new_issues = ["15"]
        # Should insert between 10 (pos 1) and 20 (pos 3), ignoring Annual 1
        assert _compute_auto_insert_position(existing_rows, new_issues) == 1

    def test_multiple_new_issues_sorted(self) -> None:
        """Multiple new issues are sorted and inserted as a block."""
        existing_rows = [
            (1, "10", 1),
            (2, "20", 2),
        ]
        new_issues = ["15", "5", "12"]  # Input order doesn't matter
        # Sorted: 5, 12, 15. First is 5, which is < 10, so insert at beginning
        assert _compute_auto_insert_position(existing_rows, new_issues) == 0

    def test_multiple_new_issues_sorted_between(self) -> None:
        """Multiple new issues inserted between existing."""
        existing_rows = [
            (1, "10", 1),
            (2, "20", 2),
            (3, "30", 3),
        ]
        new_issues = ["15", "12", "18"]  # Sorted: 12, 15, 18. First is 12, between 10 and 20
        assert _compute_auto_insert_position(existing_rows, new_issues) == 1

    def test_existing_non_numeric_at_various_positions(self) -> None:
        """Existing non-numeric issues at various positions don't affect numeric insertion."""
        existing_rows = [
            (1, "Annual 1", 1),
            (2, "10", 2),
            (3, "Special", 3),
            (4, "20", 4),
        ]
        new_issues = ["15"]
        # Numeric existing: 10 at pos 2, 20 at pos 4. 15 goes between them.
        assert _compute_auto_insert_position(existing_rows, new_issues) == 2

    def test_single_new_issue(self) -> None:
        """Single new issue works correctly."""
        existing_rows = [
            (1, "5", 1),
            (2, "15", 2),
        ]
        new_issues = ["10"]
        assert _compute_auto_insert_position(existing_rows, new_issues) == 1

    def test_new_issue_equal_to_existing_not_possible(self) -> None:
        """Equal case not possible because duplicates filtered before calling."""
        existing_rows = [
            (1, "10", 1),
        ]
        new_issues = ["10"]
        # This would be filtered out as duplicate before calling this function
        # But if called, 10 is not > 10, so it would insert after last numeric
        assert _compute_auto_insert_position(existing_rows, new_issues) == 1
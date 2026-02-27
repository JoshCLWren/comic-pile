"""Parse issue range strings into individual issue numbers."""

import re

MAX_ISSUES = 10000


def parse_issue_ranges(input_str: str) -> list[str]:
    """Parse issue range input into individual issue numbers.

    Supports formats:
    - "1-25" -> ["1", "2", ..., "25"]
    - "1, 3, 5-7" -> ["1", "3", "5", "6", "7"]
    - "25" -> ["25"] (single issue number)

    Annuals/specials should be SEPARATE THREADS with dependencies (not part of main series issue list).
    This parser only handles numeric issues.

    Args:
        input_str: Range string like "1-25" or "1, 3, 5-7"

    Returns:
        List of issue number strings

    Raises:
        ValueError: If format is invalid or contains non-numeric issues
    """
    if not input_str or not input_str.strip():
        raise ValueError("Issue range cannot be empty")

    if re.search(r"[^0-9,\-\s]", input_str.strip()):
        raise ValueError(
            "Non-numeric issues detected. "
            "Annuals and specials should be created as separate threads."
        )

    result = []

    parts = input_str.split(",")

    for part in parts:
        part = part.strip()
        if not part:
            continue

        if "-" in part:
            range_parts = part.split("-")
            if len(range_parts) != 2:
                raise ValueError(f"Invalid range format: {part}")

            try:
                start = int(range_parts[0].strip())
                end = int(range_parts[1].strip())
            except ValueError:
                raise ValueError(f"Invalid issue numbers in range: {part}") from None

            if start < 1 or end < 1:
                raise ValueError("Issue numbers must be positive")

            if start > end:
                raise ValueError(f"Range start ({start}) cannot exceed end ({end})")

            result.extend(str(i) for i in range(start, end + 1))
        else:
            try:
                issue_num = int(part)
            except ValueError:
                raise ValueError(f"Invalid issue number: {part}") from None

            if issue_num < 1:
                raise ValueError("Issue numbers must be positive")
            result.append(str(issue_num))

    seen = set()
    unique_result = []
    for issue in result:
        if issue not in seen:
            seen.add(issue)
            unique_result.append(issue)

    if len(unique_result) > MAX_ISSUES:
        raise ValueError(f"Cannot create more than {MAX_ISSUES} issues at once")

    return unique_result


def get_total_from_range(input_str: str) -> int:
    """Get total count of issues from range string.

    Convenience function for UI preview.

    Args:
        input_str: Range string like "1-25"

    Returns:
        Total number of issues
    """
    issues = parse_issue_ranges(input_str)
    return len(issues)

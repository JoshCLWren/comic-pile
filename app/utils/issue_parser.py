"""Parse issue range strings into individual issue numbers."""

MAX_ISSUES = 10000


def parse_issue_ranges(input_str: str) -> list[str]:
    """Parse issue range input into individual issue numbers.

    Supports formats:
    - "1-25" -> ["1", "2", ..., "25"]
    - "0-18" -> ["0", "1", ..., "18"]
    - "1, 3, 5-7" -> ["1", "3", "5", "6", "7"]
    - "25" -> ["25"] (single issue number)
    - "0, 1-18, Annual 1" -> ["0", "1", ..., "18", "Annual 1"]
    - "½" -> ["½"] (literal identifier)

    Tokens containing a dash are attempted as integer ranges first (both
    endpoints must be integers >= 0).  If that fails the entire token is
    stored as a literal string identifier.

    Args:
        input_str: Range string like "1-25" or "0, Annual 1, 5-7"

    Returns:
        List of issue identifier strings

    Raises:
        ValueError: If format is invalid or result exceeds MAX_ISSUES
    """
    if not input_str or not input_str.strip():
        raise ValueError("Issue range cannot be empty")

    result: list[str] = []

    parts = input_str.split(",")

    for part in parts:
        part = part.strip()
        if not part:
            continue

        if "-" in part:
            # Try to parse as an integer range
            range_parts = part.split("-", 1)
            if len(range_parts) == 2:
                left = range_parts[0].strip()
                right = range_parts[1].strip()
                try:
                    start = int(left)
                    end = int(right)
                    if start < 0 or end < 0:
                        raise ValueError("Range endpoints must be >= 0")
                    if start > end:
                        raise ValueError(
                            f"Range start ({start}) cannot exceed end ({end})"
                        )
                    result.extend(str(i) for i in range(start, end + 1))
                    continue
                except ValueError as exc:
                    # If conversion failed because it's not an integer,
                    # fall through to store as literal
                    if "invalid literal" in str(exc):
                        result.append(part)
                        continue
                    raise
            # More than one dash and not a valid range — store as literal
            result.append(part)
        else:
            # Single token — accept any non-empty string as a literal identifier
            result.append(part)

    seen: set[str] = set()
    unique_result: list[str] = []
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

#!/usr/bin/env python3
"""Debug the normalize_issue_number function."""

import re

def normalize_issue_number(value: str) -> str:
    """Normalize an issue number for exact comparison."""
    normalized = re.sub(r"[^0-9.]", "", value.lower().strip())
    print(f"Input: '{value}' -> After regex: '{normalized}'")
    # Remove trailing decimal point and any trailing zeros after decimal
    if "." in normalized:
        # Split into integer and fractional parts
        parts = normalized.split(".")
        if len(parts) == 2:
            integer_part = parts[0]
            fractional_part = parts[1].rstrip("0")
            if fractional_part:
                normalized = f"{integer_part}.{fractional_part}"
            else:
                normalized = integer_part
    # Remove trailing decimal point if it's the only character left
    normalized = normalized.rstrip(".")
    print(f"After processing: '{normalized}'")
    return normalized

# Test the problematic case
result = normalize_issue_number("1.0")
print(f"Final result: '{result}'")
print(f"Expected: '1'")
print(f"Match: {result == '1'}")
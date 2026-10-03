"""Fixed tag vocabulary and color palette.

Tag names are normalized for matching (trimmed, lowercased) while the stored
``name`` preserves the requested casing. The 32-color palette is the single
source of truth for both the API and the frontend tag picker: a tag's color
must be one of the 32 palette entries and red is the default.

The set of taggable target types is fixed at ``Issue``, ``Thread``, and
``ContinuityPlan`` (the Reading Plan model). Adding a future target type is a
two-file change: register the type name here and add a target validator in
``app/services/tag_service.py``.
"""

TAG_COLOR_PALETTE: dict[str, str] = {
    "red": "#DC2626",
    "orange": "#F97316",
    "amber": "#F59E0B",
    "yellow": "#EAB308",
    "lime": "#84CC16",
    "green": "#22C55E",
    "emerald": "#10B981",
    "teal": "#14B8A6",
    "cyan": "#06B6D4",
    "sky": "#0EA5E9",
    "blue": "#3B82F6",
    "indigo": "#6366F1",
    "violet": "#8B5CF6",
    "purple": "#A855F7",
    "fuchsia": "#D946EF",
    "pink": "#EC4899",
    "rose": "#F43F5E",
    "crimson": "#B91C1C",
    "burgundy": "#7F1D1D",
    "maroon": "#78350F",
    "brown": "#92400E",
    "gold": "#D97706",
    "bronze": "#B45309",
    "khaki": "#A16207",
    "olive": "#65A30D",
    "forest": "#15803D",
    "mint": "#34D399",
    "ice": "#22D3EE",
    "cobalt": "#2563EB",
    "royal": "#4F46E5",
    "violet-deep": "#7C3AED",
    "magenta": "#E879F9",
}
"""32 supported tag colors, keyed by human name and mapped to ``#RRGGBB``."""

TAG_COLOR_NAMES: tuple[str, ...] = tuple(TAG_COLOR_PALETTE.keys())
"""Ordered, deduplicated names from the color palette."""

DEFAULT_TAG_COLOR_NAME: str = "red"
"""The default tag color name."""

DEFAULT_TAG_COLOR_HEX: str = "#DC2626"
"""The default tag color value (``#RRGGBB``)."""

TAG_TARGET_TYPES: tuple[str, ...] = ("Issue", "Thread", "ContinuityPlan")
"""Entity types that a tag assignment can point at."""

# Maximum number of edit-distance steps to consider two names "near matches".
NEAR_MATCH_DISTANCE: int = 2
# Maximum number of near-match suggestions returned by the API.
NEAR_MATCH_LIMIT: int = 8


def validate_tag_color(color: object) -> tuple[str, str]:
    """Validate and normalize a tag color against the fixed palette.

    Accepts either a palette name (e.g. ``"red"``) or a hex value matching a
    palette entry (e.g. ``"#DC2626"``), case-insensitively.

    Args:
        color: The color to validate.

    Returns:
        Tuple of ``(color_name, color_hex)``.

    Raises:
        ValueError: When ``color`` is not a string or is not in the palette.
    """
    if not isinstance(color, str):
        raise ValueError("Tag color must be a string")

    normalized = color.strip().lower()
    if not normalized:
        raise ValueError("Tag color cannot be empty")

    if normalized in TAG_COLOR_PALETTE:
        return normalized, TAG_COLOR_PALETTE[normalized]

    if normalized.startswith("#") and len(normalized) == 7:
        candidates: list[str] = [
            name for name, hex_value in TAG_COLOR_PALETTE.items()
            if hex_value.lower() == normalized
        ]
        if candidates:
            return candidates[0], normalized

    raise ValueError(
        f"Color '{color}' is not in the fixed tag color palette of "
        f"{len(TAG_COLOR_NAMES)} colors"
    )

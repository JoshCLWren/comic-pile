"""Explicit deterministic stage precedence."""

from __future__ import annotations

STAGE_PRECEDENCE: tuple[str, ...] = (
    "blocked",
    "ready",
    "review",
    "changes-requested",
    "ci",
    "building",
)
"""Ordered from highest (most terminal / review-first) to lowest."""


def stage_precedence(stage_name: str) -> int:
    """Return numeric precedence rank; lower = higher priority."""
    try:
        return STAGE_PRECEDENCE.index(stage_name)
    except ValueError:
        return len(STAGE_PRECEDENCE)


def stage_order(stages: list[str]) -> list[str]:
    """Order stages deterministically by precedence."""
    return sorted(stages, key=stage_precedence)

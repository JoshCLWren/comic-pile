"""Pure deterministic ranking and ordering for candidates."""

from __future__ import annotations

from latticery.types import Candidate


def rank_priority(value: int) -> int:
    """Normalize priority to a deterministic numeric rank."""
    return max(0, value)


def sort_key(candidate: Candidate) -> tuple[int, int, float, int]:
    """Return deterministic sort key for a candidate."""
    return candidate.sort_key()


def order_candidates(candidates: list[Candidate]) -> list[Candidate]:
    """Return candidates in deterministic order (oldest first, highest priority first)."""
    return sorted(candidates, key=sort_key)

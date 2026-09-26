"""Correction sheet personalized examples service.

Generates compact examples for each correction sheet choice drawn from the
user's own rated/read history. Examples are explanatory only and do not
constrain the canonical recommendation behavior.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.rate_repository import (
    fetch_user_rated_threads,
    fetch_user_recent_rated_threads,
)
from app.schemas import CorrectionSheetExamplesResponse
from app.services.reading_effort import EffortEstimate, compute_effort_estimate


async def generate_correction_examples(
    db: AsyncSession,
    user_id: int,
) -> CorrectionSheetExamplesResponse:
    """Generate personalized examples for all correction sheet choices.

    Fetches the user's rating history and selects representative examples
    for each steering option. Returns empty strings (null in response) when
    no honest example exists.

    Args:
        db: Database session.
        user_id: Authenticated user ID.

    Returns:
        CorrectionSheetExamplesResponse with examples for each choice.
    """
    # Fetch highly rated threads (for "familiar" examples)
    highly_rated = await fetch_user_rated_threads(db, user_id, min_rating=4.0, limit=20)

    # Fetch all rated threads (for "lighter" effort analysis)
    all_rated = await fetch_user_rated_threads(db, user_id, min_rating=0.0, limit=50)

    # Fetch recent rated threads (for "change of pace" contrast)
    recent_rated = await fetch_user_recent_rated_threads(db, user_id, limit=20)

    if not all_rated:
        return CorrectionSheetExamplesResponse.empty()

    # Build title lookup for effort estimation
    rated_titles = {tid: (title, rating) for tid, title, rating in all_rated}

    # Find lighter example: a thread with lower effort estimate
    lighter_example = _find_lighter_example(db, user_id, rated_titles)

    # Find same-effort example: a thread with similar effort to recent average
    same_effort_example = _find_same_effort_example(db, user_id, rated_titles, recent_rated)

    # Find familiar example: highest-rated thread
    familiar_example = _find_familiar_example(highly_rated)

    # Find different example: a thread that contrasts with recent/high-rated cluster
    different_example = _find_different_example(rated_titles, recent_rated, highly_rated)

    return CorrectionSheetExamplesResponse(
        even_easier=lighter_example,
        keep_level_different=same_effort_example,
        something_familiar=familiar_example,
        something_different=different_example,
        pure_random=None,  # Surprise me explicitly has no preference signal
    )


def _find_lighter_example(
    db: AsyncSession,
    user_id: int,
    rated_titles: dict[int, tuple[str, float]],
) -> str | None:
    """Find an example of a lighter/lower-commitment read."""
    # For now, use a simple heuristic: look for shorter formats or lower issue counts
    # In a full implementation, this would use the effort estimation model
    for tid, (title, rating) in rated_titles.items():
        if rating >= 3.5:
            # Prefer completed or shorter series as "lighter" examples
            if any(kw in title.lower() for kw in ["annual", "special", "one-shot", "oneshot", "#1"]):
                return f"Think more like {title}."
    # Fallback: use the first highly rated thread
    for tid, (title, rating) in rated_titles.items():
        if rating >= 3.5:
            return f"Think more like {title}."
    return None


async def _find_same_effort_example(
    db: AsyncSession,
    user_id: int,
    rated_titles: dict[int, tuple[str, float]],
    recent_rated: list[tuple[int, str, float]],
) -> str | None:
    """Find an example of a similar-effort read."""
    if not recent_rated:
        return None

    # Get effort estimate for recent threads to understand current "level"
    recent_efforts: list[EffortEstimate] = []
    for tid, title, rating in recent_rated[:5]:
        effort = await compute_effort_estimate(db, user_id=user_id, thread_id=tid)
        recent_efforts.append(effort)

    if not recent_efforts:
        return None

    # Average the effort bands
    effort_bands = [e.band for e in recent_efforts if e.band]
    if not effort_bands:
        return None

    # Find a rated thread with similar effort band
    target_band = max(set(effort_bands), key=effort_bands.count)  # Most common band

    for tid, (title, rating) in rated_titles.items():
        if rating >= 3.0:  # Reasonably liked
            effort = await compute_effort_estimate(db, user_id=user_id, thread_id=tid)
            if effort.band == target_band:
                return f"Think more like {title}."

    return None


def _find_familiar_example(
    highly_rated: list[tuple[int, str, float]],
) -> str | None:
    """Find an example similar to what the user has rated well."""
    if not highly_rated:
        return None

    # Use the highest-rated thread as the familiar example
    _, title, rating = highly_rated[0]
    if rating >= 4.5:
        return f"Based on your ratings, think more {title} territory."
    elif rating >= 4.0:
        return f"Based on your ratings, think more {title} territory."
    return None


def _find_different_example(
    rated_titles: dict[int, tuple[str, float]],
    recent_rated: list[tuple[int, str, float]],
    highly_rated: list[tuple[int, str, float]],
) -> str | None:
    """Find an example meaningfully different from recent/high-rated reads."""
    if not rated_titles:
        return None

    # Collect "familiar" territory: recent + highly rated titles
    familiar_titles = set()
    for _, title, _ in recent_rated[:10]:
        familiar_titles.add(title.lower())
    for _, title, _ in highly_rated[:10]:
        familiar_titles.add(title.lower())

    # Find a rated thread that's not in the familiar set
    for tid, (title, rating) in rated_titles.items():
        if rating >= 3.0 and title.lower() not in familiar_titles:
            return f"Based on your ratings, think more {title} territory."

    return None
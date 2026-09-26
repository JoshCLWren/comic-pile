"""Correction sheet personalized examples service (issue #2744).

Builds one short, honest example line per steering choice in the Roll
correction sheet, drawn only from the signed-in user's own rated/read history.

Two rules drive every decision here:

1. **Examples are explanatory, never constraints.** Choosing an option still
   applies the canonical session-mode patch. Nothing here influences Roll
   selection.
2. **No fabricated examples.** Effort/commitment wording is grounded in the
   canonical reading-effort bands from :mod:`app.services.reading_effort` rather
   than a second competing definition invented for the UI, and an option with
   no honest example returns ``None`` so the sheet degrades to plain copy.

The whole sheet is served by a bounded number of queries: two rating reads, one
shared observation read, and one batched series-metadata read. Effort is never
estimated one thread at a time here, which would re-scan the reader's entire
roll-to-rate history once per candidate.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.rate_repository import (
    fetch_confirmed_series_identity_metadata,
    fetch_user_rated_threads,
    fetch_user_recent_rated_threads,
)
from app.schemas import CorrectionChoiceId, CorrectionSheetExamplesResponse
from app.services.reading_effort import (
    EffortEstimate,
    aggregate_observations,
    collect_classified_observations,
    era_prior_minutes,
    neutral_estimate,
    publication_year_from_metadata,
    resolve_effort_estimate,
)

#: A comic is only used as a positive illustration when the reader actually
#: liked it. This matches the sheet's "comics I've rated well" framing.
LIKED_RATING_FLOOR: Final[float] = 3.5
#: Highest-rated threshold backing the "stay close to what I've liked" example.
FAVORITE_RATING_FLOOR: Final[float] = 4.0
#: How many of the reader's most recent rated reads define their current level.
RECENT_EFFORT_SAMPLE_SIZE: Final[int] = 5
#: Bound on candidate rows pulled per rating query.
RATED_CANDIDATE_LIMIT: Final[int] = 50
RECENT_CANDIDATE_LIMIT: Final[int] = 20

#: Canonical band names from :mod:`app.services.reading_effort`. "Give me
#: something lighter" only ever shows a comic the canonical model already bands
#: as ``light``; the UI never invents its own notion of an easy read.
LIGHT_BAND: Final[str] = "light"
#: Bands that carry a real commitment signal. ``unknown`` means the canonical
#: model has nothing to say, so it is never presented as a deliberate contrast.
KNOWN_EFFORT_BANDS: Final[frozenset[str]] = frozenset({LIGHT_BAND, "balanced", "deep"})

#: Shared safe fallback so a thread with no estimate is treated as "no signal"
#: without re-querying or branching on ``None`` at every call site.
UNKNOWN_ESTIMATE: Final[EffortEstimate] = neutral_estimate()

#: One rated comic: (thread_id, title, rating).
RatedComic = tuple[int, str, float]


async def generate_correction_examples(
    db: AsyncSession,
    user_id: int,
) -> CorrectionSheetExamplesResponse:
    """Generate personalized examples for all correction sheet choices.

    Reads the reader's rating history once, derives canonical effort bands for
    the bounded candidate set with shared queries, and returns at most one short
    example line per choice. Choices without an honest example return ``None``.

    Args:
        db: Database session.
        user_id: Authenticated user ID.

    Returns:
        CorrectionSheetExamplesResponse with examples for each choice.
    """
    liked = await fetch_user_rated_threads(
        db,
        user_id,
        min_rating=LIKED_RATING_FLOOR,
        limit=RATED_CANDIDATE_LIMIT,
    )
    if not liked:
        return CorrectionSheetExamplesResponse.empty()

    recent = await fetch_user_recent_rated_threads(
        db,
        user_id,
        limit=RECENT_CANDIDATE_LIMIT,
    )

    # One shared observation read plus one batched metadata read replace a
    # per-thread estimate loop, so the query count is independent of history size.
    bands = await _resolve_effort_bands(
        db,
        user_id,
        {thread_id for thread_id, _title, _rating in liked}
        | {thread_id for thread_id, _title, _rating in recent},
    )

    recent_ids = [thread_id for thread_id, _title, _rating in recent][
        :RECENT_EFFORT_SAMPLE_SIZE
    ]
    current_band = _modal_known_band(bands[thread_id].band for thread_id in recent_ids)

    return CorrectionSheetExamplesResponse.from_examples(
        {
            CorrectionChoiceId.EVEN_EASIER: _find_lighter_example(liked, bands),
            CorrectionChoiceId.KEEP_LEVEL_DIFFERENT: _find_same_effort_example(
                liked, bands, current_band
            ),
            CorrectionChoiceId.SOMETHING_FAMILIAR: _find_familiar_example(liked),
            CorrectionChoiceId.SOMETHING_DIFFERENT: _find_different_example(
                liked, recent_ids, bands
            ),
            # "Surprise me" explicitly disables similarity and effort steering, so
            # it never shows a preference-derived example; its copy already
            # says so.
            CorrectionChoiceId.PURE_RANDOM: None,
        }
    )


async def _resolve_effort_bands(
    db: AsyncSession,
    user_id: int,
    thread_ids: set[int],
) -> dict[int, EffortEstimate]:
    """Resolve canonical effort estimates for a bounded thread set.

    Mirrors :func:`app.services.reading_effort.compute_effort_estimate` at
    thread granularity (no issue-level aggregate, matching the other callers for
    this surface) while sharing the observation read and the series metadata
    read across every thread.

    Args:
        db: Database session.
        user_id: Owner of the reading history.
        thread_ids: Threads to estimate.

    Returns:
        Mapping of thread ID to its canonical effort estimate.
    """
    if not thread_ids:
        return {}

    observations = await collect_classified_observations(db, user_id)
    _by_issue, by_thread = aggregate_observations(observations)
    metadata_by_thread = await fetch_confirmed_series_identity_metadata(
        db,
        sorted(thread_ids),
    )

    estimates: dict[int, EffortEstimate] = {}
    for thread_id in sorted(thread_ids):
        publication_year = None
        for metadata_json in metadata_by_thread.get(thread_id, []):
            publication_year = publication_year_from_metadata(metadata_json)
            if publication_year is not None:
                break
        estimates[thread_id] = resolve_effort_estimate(
            None,
            by_thread.get(thread_id),
            era_prior_minutes(publication_year),
        )
    return estimates


def _modal_known_band(bands: Iterable[str]) -> str | None:
    """Return the most common effort band that actually carries a signal.

    Args:
        bands: Band names for the reader's recent reads.

    Returns:
        The modal band restricted to known bands, or None when no read in the
        window produced a usable band.
    """
    known = [band for band in bands if band in KNOWN_EFFORT_BANDS]
    if not known:
        return None
    counts = Counter(known)
    top_count = max(counts.values())
    # Sorted so the winner is stable when two bands tie.
    return min(band for band, count in counts.items() if count == top_count)


def _find_lighter_example(
    liked: Sequence[RatedComic],
    bands: Mapping[int, EffortEstimate],
) -> str | None:
    """Find a liked comic the canonical model already bands as a lighter read.

    ``liked`` arrives ordered by rating descending, so the first match is the
    best-rated light example. When the reader has no light-banded rated read this
    returns None instead of labelling an arbitrary comic as lighter.

    Args:
        liked: Reader's liked rated reads, best rating first.
        bands: Canonical effort estimate per thread.

    Returns:
        A short example line, or None when no honest lighter example exists.
    """
    for thread_id, title, _rating in liked:
        if _band_of(bands, thread_id) == LIGHT_BAND:
            return f"Think more like {title}."
    return None


def _find_same_effort_example(
    liked: Sequence[RatedComic],
    bands: Mapping[int, EffortEstimate],
    current_band: str | None,
) -> str | None:
    """Find a liked comic at the reader's current commitment level.

    Args:
        liked: Reader's liked rated reads, best rating first.
        bands: Canonical effort estimate per thread.
        current_band: The reader's modal known effort band, or None.

    Returns:
        A short example line, or None when the reader's current level is unknown
        or no liked read matches it.
    """
    if current_band is None:
        return None
    for thread_id, title, _rating in liked:
        if _band_of(bands, thread_id) == current_band:
            return f"Think more like {title}."
    return None


def _find_familiar_example(liked: Sequence[RatedComic]) -> str | None:
    """Find the example representing the reader's positive history.

    ``liked`` is ordered by rating descending, so the first entry that clears
    the favorite threshold is the reader's best-rated read: the closest
    available proxy for "similar to what I've liked".

    Args:
        liked: Reader's liked rated reads, best rating first.

    Returns:
        A short example line, or None when nothing was rated highly enough.
    """
    for _thread_id, title, rating in liked:
        if rating >= FAVORITE_RATING_FLOOR:
            return f"Based on your ratings, think more {title} territory."
    return None


def _find_different_example(
    liked: Sequence[RatedComic],
    recent_ids: Sequence[int],
    bands: Mapping[int, EffortEstimate],
) -> str | None:
    """Find a liked comic that meaningfully contrasts with the recent cluster.

    Contrast is measured with the canonical effort band, the same signal the
    sheet already explains, so the example illustrates what the choice actually
    does instead of guessing from title words. Recent reads are excluded so the
    example really is somewhere else.

    Args:
        liked: Reader's liked rated reads, best rating first.
        recent_ids: Thread IDs of the reader's most recent rated reads.
        bands: Canonical effort estimate per thread.

    Returns:
        A short example line, or None when the history holds no honest contrast.
    """
    recent = set(recent_ids)
    if not recent:
        return None
    recent_bands = {
        _band_of(bands, thread_id)
        for thread_id in recent
        if _band_of(bands, thread_id) in KNOWN_EFFORT_BANDS
    }
    for thread_id, title, _rating in liked:
        if thread_id in recent:
            continue
        band = _band_of(bands, thread_id)
        if band in KNOWN_EFFORT_BANDS and band not in recent_bands:
            return f"Based on your ratings, think more {title} territory."
    return None


def _band_of(bands: Mapping[int, EffortEstimate], thread_id: int) -> str:
    """Return the canonical band for a thread, or ``unknown`` when unresolved.

    Args:
        bands: Canonical effort estimate per thread.
        thread_id: Thread whose band is needed.

    Returns:
        The canonical band name, or the neutral ``unknown`` band.
    """
    estimate = bands.get(thread_id)
    return estimate.band if estimate is not None else UNKNOWN_ESTIMATE.band

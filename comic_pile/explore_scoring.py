"""Explore intent scoring for novel-but-adjacent roll candidates.

The Explore intent favors candidates the reader has had limited prior exposure
to, while still respecting confirmed taste signals. It is deliberately NOT an
inversion of the Familiar intent:

- every candidate keeps a positive base weight, so familiar favorites are never
  categorically excluded from the die pool;
- only bounded bonuses are applied, so effects stay explainable and capped;
- missing exposure data or missing metadata is neutral rather than treated as
  maximal novelty or maximal relevance.

All weights live inside the existing die pool: this module never changes which
candidates are eligible, only their relative selection weight within the pool.
Pure-random selection remains a separate, untouched bypass path.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass, field

EXPLORE_INTENT = "explore"

# Every candidate starts from this weight; bonuses can raise it but nothing
# lowers it below this floor.
EXPLORE_BASE_WEIGHT = 1.0

# Maximum bonus granted for being unread/less-exposed. A fully novel candidate
# therefore has at most ``1.0 + EXPLORE_NOVELTY_MAX_BONUS`` times the weight of
# an exhaustingly familiar one before adjacency is considered.
EXPLORE_NOVELTY_MAX_BONUS = 0.75

# Series-level exposure counts less than direct thread exposure when deciding
# how novel a candidate still feels.
EXPLORE_SERIES_EXPOSURE_DISCOUNT = 0.5

# Adjacency only rewards genuinely novel candidates. Once effective exposure
# passes this threshold the candidate is no longer "exploration" material.
EXPLORE_ADJACENCY_MAX_EFFECTIVE_EXPOSURE = 2.0

# Small per-anchor bonus when a novel candidate shares a confirmed taste anchor
# (creator, character/team, publisher) with the reader's confirmed favorites.
EXPLORE_ADJACENCY_PER_ANCHOR_BONUS = 0.125

# An era match ("nearby era") counts as at most one additional anchor hit and
# requires the candidate era year to be within this many years of an anchor.
EXPLORE_ERA_ADJACENCY_YEARS = 5

# Hard ceiling on the total adjacency bonus regardless of anchor count.
EXPLORE_ADJACENCY_MAX_BONUS = 0.25

# Absolute ceiling on any explore weight, keeping contextual effects capped
# inside the existing die pool.
EXPLORE_WEIGHT_CAP = 2.0

_ANCHOR_KINDS = ("creator", "character", "team", "publisher")

REASON_NOVEL = "explore:novel"
REASON_TASTE_ADJACENT = "explore:taste_adjacent"
REASON_ERA_ADJACENT = "explore:era_adjacent"


def normalize_anchor_value(value: str) -> str:
    """Normalize an anchor or metadata value for case-insensitive matching.

    Args:
        value: Raw provider or reader-facing string value.

    Returns:
        Casefolded value with collapsed whitespace, suitable as a set key.
    """
    return " ".join(value.casefold().split())


@dataclass(frozen=True)
class TasteAnchors:
    """Confirmed taste anchors derived from the reader's strongly-rated history.

    Each collection holds normalized values. Empty collections are valid and
    simply mean no confirmed adjacency evidence exists yet.
    """

    creators: frozenset[str] = field(default_factory=frozenset)
    characters: frozenset[str] = field(default_factory=frozenset)
    teams: frozenset[str] = field(default_factory=frozenset)
    publishers: frozenset[str] = field(default_factory=frozenset)
    era_years: tuple[int, ...] = ()

    def is_empty(self) -> bool:
        """Return whether no confirmed anchors exist.

        Returns:
            True when there is no adjacency evidence at all.
        """
        return not (
            self.creators or self.characters or self.teams or self.publishers or self.era_years
        )


@dataclass(frozen=True)
class CandidateFeatures:
    """Normalized metadata features describing one roll-pool candidate.

    All collections are optional evidence; empty collections keep the candidate
    fully eligible while contributing no adjacency signal.
    """

    creators: frozenset[str] = field(default_factory=frozenset)
    characters: frozenset[str] = field(default_factory=frozenset)
    teams: frozenset[str] = field(default_factory=frozenset)
    publishers: frozenset[str] = field(default_factory=frozenset)
    era_years: tuple[int, ...] = ()

    def is_empty(self) -> bool:
        """Return whether the candidate has no usable metadata features.

        Returns:
            True when no feature evidence was resolved.
        """
        return not (
            self.creators or self.characters or self.teams or self.publishers or self.era_years
        )


@dataclass(frozen=True)
class ExploreCandidate:
    """One die-pool candidate plus the evidence needed to score it."""

    thread_id: int
    # Prior exposures of this exact thread (rolls, rates, skips, snoozes).
    # Zero means the reader has never been exposed to it in recorded history.
    exposure_count: int = 0
    # Exposure accumulated across sibling threads of the same confirmed series,
    # or None when series identity is unknown. Unknown stays neutral.
    series_exposure_count: int | None = None
    features: CandidateFeatures = field(default_factory=CandidateFeatures)


@dataclass(frozen=True)
class ExploreScore:
    """Scored explore weight plus the reason codes that explain it."""

    thread_id: int
    weight: float
    novelty_factor: float
    novelty_bonus: float
    adjacency_bonus: float
    reason_codes: tuple[str, ...]


def novelty_factor(thread_exposure: int, series_exposure: int | None = None) -> float:
    """Compute how novel a candidate still feels from limited prior exposure.

    Direct thread exposure dominates; series exposure counts at a discount.
    Unknown series exposure (``None``) is neutral - it contributes nothing.

    Args:
        thread_exposure: Prior exposure count for this exact thread.
        series_exposure: Exposure across sibling threads of the same series.

    Returns:
        Factor in ``(0, 1]``; 1.0 for something entirely unexposed and trending
        toward 0 as exposure accumulates.
    """
    effective = max(0, thread_exposure)
    if series_exposure is not None and series_exposure > 0:
        effective += series_exposure * EXPLORE_SERIES_EXPOSURE_DISCOUNT
    return 1.0 / (1.0 + float(effective))


def _era_is_nearby(candidate_years: tuple[int, ...], anchor_years: tuple[int, ...]) -> bool:
    return any(
        abs(candidate_year - anchor_year) <= EXPLORE_ERA_ADJACENCY_YEARS
        for candidate_year in candidate_years
        for anchor_year in anchor_years
    )


def adjacency_bonus(
    features: CandidateFeatures,
    anchors: TasteAnchors,
    novelty: float,
) -> tuple[float, bool]:
    """Compute the capped adjacency bonus against confirmed taste anchors.

    Missing metadata on either side contributes nothing: unknown features stay
    neutral instead of being scored as maximally relevant or irrelevant.

    Args:
        features: Normalized metadata features of the candidate.
        anchors: Confirmed taste anchors.
        novelty: Novelty factor from :func:`novelty_factor`; adjacency only
            applies to candidates that are still genuinely under-exposed.

    Returns:
        Tuple of the bonus amount (never below zero, never above
        ``EXPLORE_ADJACENCY_MAX_BONUS``) and whether an era match occurred.
    """
    if anchors.is_empty() or features.is_empty():
        return 0.0, False
    if 1.0 / novelty > 1.0 + EXPLORE_ADJACENCY_MAX_EFFECTIVE_EXPOSURE:
        return 0.0, False

    matched = (
        len(features.creators & anchors.creators)
        + len(features.characters & anchors.characters)
        + len(features.teams & anchors.teams)
        + len(features.publishers & anchors.publishers)
    )
    era_match = _era_is_nearby(features.era_years, anchors.era_years)
    raw_bonus = matched * EXPLORE_ADJACENCY_PER_ANCHOR_BONUS
    if era_match:
        raw_bonus += EXPLORE_ADJACENCY_PER_ANCHOR_BONUS
    return min(raw_bonus, EXPLORE_ADJACENCY_MAX_BONUS), era_match


def score_explore_candidate(candidate: ExploreCandidate, anchors: TasteAnchors) -> ExploreScore:
    """Score one candidate's explore weight from novelty plus adjacency.

    The result is always within ``[EXPLORE_BASE_WEIGHT, EXPLORE_WEIGHT_CAP]``:
    familiar candidates keep meaningful weight and bonuses stay capped.

    Args:
        candidate: Die-pool candidate with its exposure and feature evidence.
        anchors: Confirmed taste anchors for the reader.

    Returns:
        ExploreScore with the final weight and explanation codes.
    """
    novelty = novelty_factor(candidate.exposure_count, candidate.series_exposure_count)
    novelty_bonus_amount = EXPLORE_NOVELTY_MAX_BONUS * novelty
    bonus_amount, era_match = adjacency_bonus(candidate.features, anchors, novelty)

    weight = min(
        EXPLORE_BASE_WEIGHT + novelty_bonus_amount + bonus_amount,
        EXPLORE_WEIGHT_CAP,
    )

    reason_codes: list[str] = []
    if novelty_bonus_amount > 0.0:
        reason_codes.append(REASON_NOVEL)
    if bonus_amount > 0.0:
        reason_codes.append(REASON_TASTE_ADJACENT)
    if era_match:
        reason_codes.append(REASON_ERA_ADJACENT)

    return ExploreScore(
        thread_id=candidate.thread_id,
        weight=weight,
        novelty_factor=novelty,
        novelty_bonus=novelty_bonus_amount,
        adjacency_bonus=bonus_amount,
        reason_codes=tuple(reason_codes),
    )


def score_explore_candidates(
    candidates: Sequence[ExploreCandidate],
    anchors: TasteAnchors,
) -> list[ExploreScore]:
    """Score every die-pool candidate in order.

    Args:
        candidates: Bounded roll-pool candidates.
        anchors: Confirmed taste anchors for the reader.

    Returns:
        One ExploreScore per input candidate, preserving input order.
    """
    return [score_explore_candidate(candidate, anchors) for candidate in candidates]


def select_explore_index(weights: Sequence[float], rng: random.Random) -> int:
    """Pick one index proportionally to the given positive weights.

    Every weight must be strictly positive so no candidate is ever fully
    excluded; callers get that guarantee from :func:`score_explore_candidates`.

    Args:
        weights: Positive per-candidate weights.
        rng: Random source, injectable for deterministic tests.

    Returns:
        Selected index into the weight sequence.

    Raises:
        ValueError: If the sequence is empty or any weight is not positive.
    """
    if not weights:
        raise ValueError("Cannot select from an empty weight sequence")
    if any(weight <= 0.0 for weight in weights):
        raise ValueError("Explore selection requires strictly positive weights")

    total = sum(weights)
    threshold = rng.random() * total
    running = 0.0
    for index, weight in enumerate(weights):
        running += weight
        if running >= threshold:
            return index
    return len(weights) - 1


__all__ = [
    "CandidateFeatures",
    "EXPLORE_ADJACENCY_MAX_BONUS",
    "EXPLORE_ADJACENCY_MAX_EFFECTIVE_EXPOSURE",
    "EXPLORE_ADJACENCY_PER_ANCHOR_BONUS",
    "EXPLORE_BASE_WEIGHT",
    "EXPLORE_ERA_ADJACENCY_YEARS",
    "EXPLORE_INTENT",
    "EXPLORE_NOVELTY_MAX_BONUS",
    "EXPLORE_SERIES_EXPOSURE_DISCOUNT",
    "EXPLORE_WEIGHT_CAP",
    "ExploreCandidate",
    "ExploreScore",
    "REASON_ERA_ADJACENT",
    "REASON_NOVEL",
    "REASON_TASTE_ADJACENT",
    "TasteAnchors",
    "_ANCHOR_KINDS",
    "adjacency_bonus",
    "normalize_anchor_value",
    "novelty_factor",
    "score_explore_candidate",
    "score_explore_candidates",
    "select_explore_index",
]
